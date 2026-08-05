from knowledge_system.migration import MigrationGuard


def approve_migration(approved: bool) -> bool:
    return MigrationGuard().require_approved(approved)
