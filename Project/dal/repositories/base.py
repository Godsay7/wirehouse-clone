"""Shared repository helpers."""


class Repository:
    def __init__(self, connection):
        self.connection = connection

    def _execute(self, query, parameters=()):
        return self.connection.execute(query, parameters)

    def _one(self, query, parameters=()):
        return self.connection.execute(query, parameters).fetchone()

    def _all(self, query, parameters=()):
        return self.connection.execute(query, parameters).fetchall()

    def _dicts(self, query, parameters=()):
        return [dict(row) for row in self._all(query, parameters)]
