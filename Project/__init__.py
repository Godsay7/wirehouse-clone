"""Switch Inventory: SNMP collector + web UI for switches, racks and cabling.

Layers (each one may only import the layers below it):

    web/        Presentation layer (Flask blueprints, templates, static).
    collector/  Presentation layer for the SNMP collector CLI + SNMP access.
    bll/        Business logic: pure domain rules and use-case services.
    dal/        Data access: SQLite connection, schema/migrations, repositories.
    core/       Small dependency-free helpers shared by every layer.
"""
