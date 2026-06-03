from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.papers.reference_import import parse_reference_candidates


class PaperReferenceImportTests(TestCase):
    def setUp(self) -> None:
        self.user = get_user_model().objects.create_user(username="member", password="member-password")

    def test_parses_ris_candidates(self) -> None:
        content = """TY  - JOUR
TI  - PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks
AU  - Zhao, Zhiyuan
AU  - Ding, Xueying
PY  - 2024
JO  - ICLR
UR  - https://arxiv.org/abs/2307.11833
AB  - Transformer framework for physics-informed neural networks.
KW  - PINN
KW  - Transformer
ER  -
"""

        candidates = parse_reference_candidates(content)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "ris_import")
        self.assertEqual(candidates[0]["title"], "PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks")
        self.assertEqual(candidates[0]["authors"], ["Zhao, Zhiyuan", "Ding, Xueying"])
        self.assertEqual(candidates[0]["year"], 2024)
        self.assertEqual(candidates[0]["arxiv_id"], "2307.11833")
        self.assertEqual(candidates[0]["keywords"], ["PINN", "Transformer"])

    def test_parses_bibtex_candidates(self) -> None:
        content = """@inproceedings{zhao2024pinnsformer,
  title={PINNsFormer: A Transformer-Based Framework For Physics-Informed Neural Networks},
  author={Zhiyuan Zhao and Xueying Ding and B. Aditya Prakash},
  year={2024},
  booktitle={ICLR},
  url={https://arxiv.org/abs/2307.11833},
  keywords={PINN, Transformer, PDE}
}"""

        candidates = parse_reference_candidates(content)

        self.assertEqual(candidates[0]["source"], "bibtex_import")
        self.assertEqual(candidates[0]["venue"], "ICLR")
        self.assertEqual(candidates[0]["authors"], ["Zhiyuan Zhao", "Xueying Ding", "B. Aditya Prakash"])
        self.assertEqual(candidates[0]["keywords"], ["PINN", "Transformer", "PDE"])

    def test_reference_import_api_requires_login_and_returns_candidates(self) -> None:
        response = self.client.post(
            "/api/papers/metadata-reference-candidates/",
            data={"content": "TY  - JOUR\nTI  - Neural Finite Volume Methods\nPY  - 2026\nER  -"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

        self.client.login(username=self.user.username, password="member-password")
        response = self.client.post(
            "/api/papers/metadata-reference-candidates/",
            data={"content": "TY  - JOUR\nTI  - Neural Finite Volume Methods\nPY  - 2026\nER  -"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["candidates"][0]["year"], 2026)
