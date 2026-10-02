from yushuos_sdk import Request


def test_request_round_trip():
    request = Request("example-1", "example.echo", "read", {"message": "hello"})
    assert request.to_dict()["fields"] == {"message": "hello"}
    assert len(request.fingerprint()) == 64
