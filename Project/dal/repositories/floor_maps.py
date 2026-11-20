"""Floor maps, their rooms (polygons) and workplaces."""

import json

from .base import Repository

WORKPLACE_FIELDS = ("x", "y", "device_type", "role", "pc_name", "ip", "note", "socket", "dante_ip", "dante_socket")
WORKPLACE_COLUMNS = "id, map_id, " + ", ".join(WORKPLACE_FIELDS)


class FloorMapRepository(Repository):

    # Maps

    def list_maps(self):
        return self._dicts(
            """
            SELECT m.id, m.name, m.width, m.height,
                   (SELECT COUNT(*) FROM floor_map_workplaces w
                    WHERE w.map_id = m.id AND w.device_type = 'pc') AS workplace_count
            FROM floor_maps m
            ORDER BY m.position, m.id
            """
        )

    def get_map(self, map_id):
        row = self._one("SELECT id, name, width, height FROM floor_maps WHERE id = ?", (map_id,))
        return dict(row) if row is not None else None

    def map_name_taken(self, name, except_id=0):
        return self._one(
            "SELECT 1 FROM floor_maps WHERE name = ? COLLATE NOCASE AND id != ?",
            (name, except_id),
        ) is not None

    def create_map(self, name, width, height, now):
        position = self._one("SELECT COALESCE(MAX(position), -1) + 1 FROM floor_maps")[0]
        cursor = self._execute(
            "INSERT INTO floor_maps (name, width, height, position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (name, width, height, position, now, now),
        )
        return cursor.lastrowid

    def update_map(self, map_id, name, width, height, now):
        self._execute(
            "UPDATE floor_maps SET name = ?, width = ?, height = ?, updated_at = ? WHERE id = ?",
            (name, width, height, now, map_id),
        )

    def set_map_positions(self, map_ids):
        """Tab order: map_ids[0] becomes the first tab."""

        self.connection.executemany(
            "UPDATE floor_maps SET position = ? WHERE id = ?",
            [(position, map_id) for position, map_id in enumerate(map_ids)],
        )

    def delete_map(self, map_id):
        self._execute("DELETE FROM floor_map_rooms WHERE map_id = ?", (map_id,))
        self._execute("DELETE FROM floor_map_workplaces WHERE map_id = ?", (map_id,))
        self._execute("DELETE FROM floor_maps WHERE id = ?", (map_id,))

    # Rooms

    def list_rooms(self, map_id):
        rooms = self._dicts(
            "SELECT id, map_id, room_type, name, points FROM floor_map_rooms WHERE map_id = ? ORDER BY id",
            (map_id,),
        )
        for room in rooms:
            room["points"] = json.loads(room["points"] or "[]")
        return rooms

    def get_room(self, room_id):
        row = self._one("SELECT id, map_id, room_type, name, points FROM floor_map_rooms WHERE id = ?", (room_id,))
        if row is None:
            return None
        room = dict(row)
        room["points"] = json.loads(room["points"] or "[]")
        return room

    def create_room(self, map_id, room_type, name, points, now):
        cursor = self._execute(
            "INSERT INTO floor_map_rooms (map_id, room_type, name, points, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (map_id, room_type, name, json.dumps(points), now, now),
        )
        return cursor.lastrowid

    def update_room(self, room_id, room_type, name, points, now):
        self._execute(
            "UPDATE floor_map_rooms SET room_type = ?, name = ?, points = ?, updated_at = ? WHERE id = ?",
            (room_type, name, json.dumps(points), now, room_id),
        )

    def delete_room(self, room_id):
        self._execute("DELETE FROM floor_map_rooms WHERE id = ?", (room_id,))

    # Workplaces

    def list_workplaces(self, map_id):
        return self._dicts(
            f"SELECT {WORKPLACE_COLUMNS} FROM floor_map_workplaces WHERE map_id = ? ORDER BY id",
            (map_id,),
        )

    def get_workplace(self, workplace_id):
        row = self._one(
            f"SELECT {WORKPLACE_COLUMNS} FROM floor_map_workplaces WHERE id = ?",
            (workplace_id,),
        )
        return dict(row) if row is not None else None

    def create_workplace(self, map_id, values, now):
        cursor = self._execute(
            """
            INSERT INTO floor_map_workplaces (map_id, x, y, device_type, role, pc_name, ip, note, socket, dante_ip, dante_socket,
                                              created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (map_id, *(values[field] for field in WORKPLACE_FIELDS), now, now),
        )
        return cursor.lastrowid

    def update_workplace(self, workplace_id, values, now):
        self._execute(
            """
            UPDATE floor_map_workplaces
            SET x = ?, y = ?, device_type = ?, role = ?, pc_name = ?, ip = ?, note = ?, socket = ?, dante_ip = ?, dante_socket = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (*(values[field] for field in WORKPLACE_FIELDS), now, workplace_id),
        )

    def delete_workplace(self, workplace_id):
        self._execute("DELETE FROM floor_map_workplaces WHERE id = ?", (workplace_id,))

    def list_roles(self):
        return [row[0] for row in self._all(
            "SELECT DISTINCT role FROM floor_map_workplaces WHERE role != '' AND device_type = 'pc' ORDER BY role COLLATE NOCASE"
        )]
