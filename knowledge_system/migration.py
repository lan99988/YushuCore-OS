class MigrationGuard:
    def require_approved(self, approved: bool) -> bool:
        if not approved:
            raise PermissionError("Human approval is required before asset migration")
        return True
