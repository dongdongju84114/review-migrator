from __future__ import annotations

from pathlib import Path

from review_migrator.schemas import CremaReviewPayload
from review_migrator.utils import write_csv

CREMA_OTHER_REVIEW_COLUMNS = [
    "리뷰 번호 (ID)",
    "상품 번호 (product_id)",
    "상품 코드 (product_code)",
    "유저 아이디 (user_id)",
    "유저 이름 (user_name)",
    "리뷰 작성일 (created_at)",
    "별점 (score)",
    "제목(title)",
    "리뷰내용 (message)",
    "진열여부 (display)",
    "동영상1 (video_url1)",
    "동영상2 (video_url2)",
    "동영상3 (video_url3)",
    "동영상4 (video_url4)",
    "이미지1 (image_url1)",
    "이미지2 (image_url2)",
    "이미지3 (image_url3)",
    "이미지4 (image_url4)",
    "댓글 작성자 이름 (comment_author)",
    "댓글 작성자 아이디 (comment_user_id)",
    "댓글 내용 (comment_message)",
    "댓글 작성일 (comment_created_at)",
]


def payload_to_csv_row(payload: CremaReviewPayload) -> dict[str, object]:
    image_urls = [*payload.image_urls[:4], "", "", "", ""]
    return {
        "리뷰 번호 (ID)": payload.code,
        "상품 번호 (product_id)": payload.product_id or "",
        "상품 코드 (product_code)": payload.product_code or "",
        "유저 아이디 (user_id)": payload.user_code or "",
        "유저 이름 (user_name)": payload.user_name,
        "리뷰 작성일 (created_at)": payload.created_at.strftime("%Y. %m. %d"),
        "별점 (score)": payload.score,
        "제목(title)": "",
        "리뷰내용 (message)": payload.message,
        "진열여부 (display)": "Y" if payload.display else "N",
        "동영상1 (video_url1)": "",
        "동영상2 (video_url2)": "",
        "동영상3 (video_url3)": "",
        "동영상4 (video_url4)": "",
        "이미지1 (image_url1)": image_urls[0],
        "이미지2 (image_url2)": image_urls[1],
        "이미지3 (image_url3)": image_urls[2],
        "이미지4 (image_url4)": image_urls[3],
        "댓글 작성자 이름 (comment_author)": "",
        "댓글 작성자 아이디 (comment_user_id)": "",
        "댓글 내용 (comment_message)": "",
        "댓글 작성일 (comment_created_at)": "",
    }


def write_crema_csv(path: str | Path, payloads: list[CremaReviewPayload]) -> int:
    return write_csv(path, [payload_to_csv_row(payload) for payload in payloads], CREMA_OTHER_REVIEW_COLUMNS)
