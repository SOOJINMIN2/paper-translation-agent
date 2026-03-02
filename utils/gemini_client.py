"""Gemini API 래퍼 - 텍스트 생성 및 Vision(이미지) 처리."""
import io
import time
import google.generativeai as genai
import PIL.Image

import config
from utils.console import warn


class GeminiClient:
    def __init__(self):
        if not config.GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY 환경변수가 설정되지 않았습니다.\n"
                ".env 파일에 GEMINI_API_KEY=your_key_here 를 추가하거나\n"
                "터미널에서 'set GEMINI_API_KEY=...' 를 실행하세요."
            )
        genai.configure(api_key=config.GEMINI_API_KEY)

    def generate(self, prompt: str, model_name: str | None = None, retries: int = 3) -> str:
        """텍스트 프롬프트로 Gemini 응답 생성."""
        model_name = model_name or config.HIGH_PRIORITY_MODEL
        model = genai.GenerativeModel(model_name)

        for attempt in range(retries):
            try:
                response = model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        temperature=0.2,
                        max_output_tokens=8192,
                    ),
                    safety_settings=[
                        {"category": "HARM_CATEGORY_HARASSMENT",       "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HATE_SPEECH",      "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT","threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT","threshold": "BLOCK_NONE"},
                    ],
                )
                return response.text
            except Exception as e:
                if attempt < retries - 1:
                    warn(f"Gemini API 오류 (재시도 {attempt+1}/{retries}): {e}")
                    time.sleep(2 ** attempt)
                else:
                    raise

    def vision_extract(self, image_bytes: bytes, prompt: str, model_name: str | None = None) -> str:
        """이미지 + 텍스트 프롬프트로 Gemini Vision 응답 생성."""
        model_name = model_name or config.VISION_MODEL
        model = genai.GenerativeModel(model_name)
        image = PIL.Image.open(io.BytesIO(image_bytes))

        response = model.generate_content(
            [prompt, image],
            generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=8192),
        )
        return response.text
