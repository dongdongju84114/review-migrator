from review_migrator.cafe24.admin import Cafe24AdminClient


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self.body = body or {}
        self.text = str(self.body)

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_cafe24_admin_client_resolves_product_code_to_product_no():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {
                    "products": [
                        {"product_code": "P000001", "product_no": 501},
                        {"product_code": "P000002", "product_no": 502},
                        {"product_code": "P000001-OPTION", "product_no": 999},
                    ]
                },
            )
        ]
    )
    client = Cafe24AdminClient(
        mall_id="sample",
        access_token="token",
        session=session,
        retry_sleep=0,
    )

    result = client.product_no_by_product_code(["P000001", "P000002"], shop_no=1)

    assert result == {"P000001": "501", "P000002": "502"}
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url == "https://sample.cafe24api.com/api/v2/admin/products"
    assert kwargs["params"]["product_code"] == "P000001,P000002"
    assert kwargs["headers"]["Authorization"] == "Bearer token"
    assert kwargs["headers"]["X-Cafe24-Api-Version"] == "2024-12-01"
