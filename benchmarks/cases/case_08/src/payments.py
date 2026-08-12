from collections.abc import Callable


class GatewayTimeout(RuntimeError):
    pass


class PaymentUnavailable(RuntimeError):
    pass


def charge(send: Callable[[], str]) -> str | None:
    try:
        return send()
    except GatewayTimeout:
        return None
