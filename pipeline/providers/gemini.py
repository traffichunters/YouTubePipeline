"""Google GenAI providers: script text (Gemini) and images (Nano Banana / Imagen 4)."""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

from ..util import die, log

# indicative $/image for cost logging (update as pricing changes)
IMAGE_COST = {"gemini-flash": 0.039, "imagen-4": 0.04}
TEXT_MODEL = "gemini-2.5-flash"
IMAGE_MODEL_IDS = {
    "gemini-flash": "gemini-2.5-flash-image",
    "imagen-4": "imagen-4.0-generate-001",
}


def _client():
    from google import genai
    return genai.Client()  # reads GOOGLE_API_KEY from env


class GeminiScript:
    name = "gemini"
    cost_usd = 0.0

    def __init__(self) -> None:
        self.client = _client()

    def text(self, system: str, user: str) -> str:
        from google.genai import types
        res = self.client.models.generate_content(
            model=TEXT_MODEL, contents=user,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        self.cost_usd += 0.01  # rough per-call estimate for the summary
        return (res.text or "").strip()

    def json(self, system: str, user: str, retries: int = 2) -> dict:
        prompt = user
        for _ in range(retries + 1):
            out = self.text(system, prompt)
            m = re.search(r"\{.*\}", out, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group(0))
                except json.JSONDecodeError:
                    pass
            prompt = user + "\n\nReturn ONLY the JSON object, nothing else."
        die(f"gemini returned invalid JSON:\n{out[:800]}")


class GeminiImage:
    def __init__(self, model: str) -> None:
        self.name = model
        self.model_id = IMAGE_MODEL_IDS[model]
        self.client = _client()
        self.cost_usd = 0.0

    def generate(self, prompt: str, out_path: Path, aspect: str = "16:9") -> Path:
        from google.genai import types
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if self.name == "imagen-4":
            res = self.client.models.generate_images(
                model=self.model_id, prompt=prompt,
                config=types.GenerateImagesConfig(number_of_images=1,
                                                  aspect_ratio=aspect),
            )
            img = res.generated_images[0].image
            out_path.write_bytes(img.image_bytes)
        else:  # gemini-2.5-flash-image ("Nano Banana")
            data = self._flash_with_retries(prompt, aspect)
            out_path.write_bytes(data)
        self.cost_usd += IMAGE_COST[self.name]
        return out_path

    def _flash_with_retries(self, prompt: str, aspect: str,
                            retries: int = 4) -> bytes:
        """Empty candidates happen (safety filter on violent beats, transients).
        Retry; from attempt 3 swap to a sanitized prompt (style only, no beat)."""
        import time
        from google.genai import types
        sanitized = (prompt.split(", depicting:")[0]
                     + ", depicting: a calm, atmospheric historical scene. "
                     "No text, no borders, museum-quality painting.")
        last = ""
        for attempt in range(retries + 1):
            use = prompt if attempt < 2 else sanitized
            try:
                res = self.client.models.generate_content(
                    model=self.model_id, contents=use,
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        image_config=types.ImageConfig(aspect_ratio=aspect)),
                )
                cand = (res.candidates or [None])[0]
                if cand is not None and cand.content is not None:
                    part = next((p for p in cand.content.parts or []
                                 if getattr(p, "inline_data", None)), None)
                    if part is not None:
                        return part.inline_data.data
                last = f"empty candidate (finish={getattr(cand, 'finish_reason', None)})"
            except Exception as e:  # noqa: BLE001 — transient API failures
                last = str(e)[:200]
            log(f"  image retry {attempt + 1}/{retries}"
                f"{' [sanitized prompt]' if attempt >= 1 else ''}: {last}")
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"image generation failed after {retries + 1} tries: {last}")
