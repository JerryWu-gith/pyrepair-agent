class Session:
    def __init__(self, user: str) -> None:
        self.user = user
        self.authenticated = True

    def logout(self) -> None:
        self.user = None
