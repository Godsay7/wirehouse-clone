"""Rack View board: a grid of rack slots per server room.

Positions are numbered row by row, six per row (position // 6 = row).

"grid" layout (default): two rows of six slots. If a room ever grows beyond
12 racks, the board is extended by complete rows of six rather than hiding
equipment.

"custom" layout: only positions holding a rack plus empty positions the user
added on purpose; each rack keeps its row.
"""

SLOT_COLUMNS = 6
MINIMUM_SLOTS = 12
MAX_POSITION = 600
LAYOUTS = ("grid", "custom")


def board_slot_count(rack_count, requested_slots=0):
    return max(
        MINIMUM_SLOTS,
        requested_slots,
        ((rack_count + SLOT_COLUMNS - 1) // SLOT_COLUMNS) * SLOT_COLUMNS,
    )


def _card_position(card):
    try:
        position = int(card.get("view_position"))
    except (TypeError, ValueError):
        return -1
    return position if 0 <= position < MAX_POSITION else -1


def place_cards(cards, layout="grid", slot_positions=()):
    """Put rack cards into board slots by their saved view_position.

    Cards without a valid free position fill the first empty slots.
    Returns [{"index": position, "card": card_or_None}, ...].
    """

    if layout == "custom":
        return _place_custom(cards, slot_positions)

    slot_count = board_slot_count(len(cards))
    slots = [None] * slot_count
    unplaced = []

    for card in cards:
        position = _card_position(card)

        if 0 <= position < slot_count and slots[position] is None:
            slots[position] = card
        else:
            unplaced.append(card)

    free_positions = [
        index
        for index, card in enumerate(slots)
        if card is None
    ]

    for card, position in zip(unplaced, free_positions):
        slots[position] = card

    return [
        {
            "index": index,
            "card": card,
        }
        for index, card in enumerate(slots)
    ]


def normalize_slot_map(raw_slots, valid_ids):
    """Validate a browser slot map: list of rack ids / empty values per slot.

    Unknown or duplicate racks are dropped. Racks missing from the map are
    put into the first free slots so nothing disappears from Rack View.
    """

    valid_set = set(valid_ids)
    slot_count = board_slot_count(len(valid_ids), len(raw_slots))
    normalized = [None] * slot_count
    seen = set()

    for position_index, value in enumerate(raw_slots[:slot_count]):
        if value in (None, "", 0, "0"):
            continue

        try:
            rack_id = int(value)
        except (TypeError, ValueError):
            continue

        if rack_id not in valid_set or rack_id in seen:
            continue

        normalized[position_index] = rack_id
        seen.add(rack_id)

    free_positions = [
        index
        for index, rack_id in enumerate(normalized)
        if rack_id is None
    ]
    missing_ids = [rack_id for rack_id in valid_ids if rack_id not in seen]

    for rack_id, position_index in zip(missing_ids, free_positions):
        normalized[position_index] = rack_id
        seen.add(rack_id)

    return normalized


def normalize_rack_order(raw_rack_ids, valid_ids):
    """Old v16/v19 payload: an ordered list of rack ids."""

    valid_set = set(valid_ids)
    rack_ids = []
    seen = set()

    for value in raw_rack_ids:
        try:
            rack_id = int(value)
        except (TypeError, ValueError):
            continue
        if rack_id <= 0 or rack_id in seen or rack_id not in valid_set:
            continue
        seen.add(rack_id)
        rack_ids.append(rack_id)

    rack_ids.extend(rack_id for rack_id in valid_ids if rack_id not in seen)
    return rack_ids


def _place_custom(cards, slot_positions):
    by_position = {}
    unplaced = []

    for card in cards:
        position = _card_position(card)
        if position >= 0 and position not in by_position:
            by_position[position] = card
        else:
            unplaced.append(card)

    empty = sorted(p for p in set(slot_positions) if 0 <= p < MAX_POSITION and p not in by_position)
    for card in unplaced:
        if empty:
            position = empty.pop(0)
        else:
            position = max(by_position, default=-1) + 1
        by_position[position] = card

    positions = sorted(set(by_position) | set(empty))
    return [{"index": position, "card": by_position.get(position)} for position in positions]


def grid_positions(rack_count):
    """Positions shown by the classic grid layout."""

    return list(range(board_slot_count(rack_count)))


def next_slot_position(positions):
    """Where "Add empty slot" puts a new slot: right after the last one."""

    return max(positions, default=-1) + 1


def normalize_custom_slots(entries, valid_ids):
    """Browser slot map of a custom board: [(position, rack_id or None), ...].

    Returns (rack_positions {rack_id: position}, slot_positions set).
    Bad positions and unknown / duplicate racks are dropped; racks missing
    from the map get the first empty slot or a new one after the last.
    """

    valid_set = set(valid_ids)
    rack_positions = {}
    slots = set()

    for position, value in entries:
        try:
            position = int(position)
        except (TypeError, ValueError):
            continue
        if not 0 <= position < MAX_POSITION or position in slots:
            continue
        slots.add(position)

        if value in (None, "", 0, "0"):
            continue
        try:
            rack_id = int(value)
        except (TypeError, ValueError):
            continue
        if rack_id in valid_set and rack_id not in rack_positions:
            rack_positions[rack_id] = position

    taken = set(rack_positions.values())
    for rack_id in valid_ids:
        if rack_id in rack_positions:
            continue
        free = sorted(slots - taken)
        position = free[0] if free else max(slots | taken, default=-1) + 1
        rack_positions[rack_id] = position
        slots.add(position)
        taken.add(position)

    return rack_positions, slots
