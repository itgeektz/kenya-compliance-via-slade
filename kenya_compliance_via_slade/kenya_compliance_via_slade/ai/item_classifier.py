import json
import re

import frappe
import requests
from frappe import _


class ETimsItemClassifier:
    def __init__(self, item_name, settings_name):
        self.item = frappe.get_doc("Item", item_name)
        self.settings = frappe.get_doc(
            "Navari KRA eTims Settings",
            settings_name,
        )

    def classify(self):
        try:
            if not self.settings.enable_ai_item_classification:
                frappe.throw(_("AI Item Classification is disabled for this setup."))

            provider = self.settings.classification_ai_provider

            if provider == "Custom":
                return self.classify_internally()

            payload = self.build_item_payload()
            result = self.call_ai(payload)
            normalized = self.normalize_prediction(result)
            self.save_prediction(normalized)
            return normalized

        except Exception:
            error = frappe.get_traceback()
            frappe.log_error(
                title="eTIMS AI Item Classification Error",
                message=error,
            )
            return {
                "success": False,
                "message": str(frappe.get_traceback()),
            }

    def classify_internally(self):
        search_text = self.build_search_text_from_item()
        if not search_text:
            return {
                "success": False,
                "message": _("Item details are too empty to perform local matching."),
            }

        matched_classification = self.find_local_match(search_text)

        if not matched_classification:
            return {
                "success": False,
                "message": _("No close match found in local classification records."),
            }

        normalized = {
            "success": True,
            "classification": matched_classification.itemclscd,
            "classification_code": matched_classification.itemclscd,
            "classification_name": matched_classification.itemclsnm,
            "tax_type_code": matched_classification.taxtycd,
            "confidence": 100,
            "reasoning": "Matched via local search engine against existing database classifications.",
            "alternative_codes": [],
            "raw_response": {
                "predicted_code": matched_classification.itemclscd,
                "predicted_name": matched_classification.itemclsnm,
                "tax_type_code": matched_classification.taxtycd,
                "confidence": 100,
            },
        }

        self.save_prediction(normalized)
        return normalized

    def build_search_text_from_item(self):
        values = [
            self.item.item_code,
            self.item.item_name,
            self.item.description,
            self.item.item_group,
            self.item.brand,
        ]
        for row in self.item.get("uoms", []):
            values.append(row.uom)

        text = " ".join([str(v) for v in values if v])
        text = re.sub(r"<[^>]*>", "", text)
        text = re.sub(r"\s+", " ", text)
        return text.lower().strip()

    def find_local_match(self, search_text):
        tokens = [t for t in re.split(r"\W+", search_text) if len(t) > 2]
        if not tokens:
            return None

        conditions = []
        for token in tokens:
            conditions.append(["itemclsnm", "like", f"%{token}%"])

        matches = frappe.get_all(
            "Navari KRA eTims Item Classification",
            fields=["name", "itemclscd", "itemclsnm", "taxtycd"],
            filters=conditions,
            limit=1,
        )

        if matches:
            return matches[0]

        fallback_conditions = []
        if self.item.item_group:
            fallback_conditions.append(
                ["itemclsnm", "like", f"%{self.item.item_group}%"]
            )
        if self.item.item_name:
            fallback_conditions.append(
                ["itemclsnm", "like", f"%{self.item.item_name[:15]}%"]
            )

        if fallback_conditions:
            fallback_matches = frappe.get_all(
                "Navari KRA eTims Item Classification",
                fields=["name", "itemclscd", "itemclsnm", "taxtycd"],
                filters=fallback_conditions,
                limit=1,
            )
            if fallback_matches:
                return fallback_matches[0]

        return None

    def build_item_payload(self):
        return {
            "item_code": self.item.item_code,
            "item_name": self.item.item_name,
            "description": self.item.description,
            "item_group": self.item.item_group,
            "stock_uom": self.item.stock_uom,
            "brand": self.item.brand,
            "is_stock_item": self.item.is_stock_item,
            "uoms": [
                {
                    "uom": row.uom,
                    "conversion_factor": row.conversion_factor,
                }
                for row in self.item.uoms
            ],
        }

    def build_search_text(self, payload):
        values = [
            payload.get("item_code"),
            payload.get("item_name"),
            payload.get("description"),
            payload.get("item_group"),
            payload.get("stock_uom"),
            payload.get("brand"),
        ]

        for row in payload.get("uoms", []):
            values.append(row.get("uom"))

        text = " ".join([str(v) for v in values if v])
        text = re.sub(r"\s+", " ", text)
        return text.lower().strip()

    def call_ai(self, item_payload):
        provider = self.settings.classification_ai_provider
        model_id = self.settings.classification_model_id or "gemini-2.0-flash"

        prompt = f"""
{self.settings.classification_system_prompt or self.default_prompt()}

**CRITICAL INSTRUCTION - NO CODE GENERATION:**

You are STRICTLY PROHIBITED from inventing, creating, or generating any classification codes on your own.

You MUST ONLY select and return codes that EXIST in the official KRA classification list.

**SOURCE OF TRUTH:**
https://github.com/muruthigitau/eTims-Classification-Codes#readme

This GitHub repository contains the complete official list of valid itemClsCd codes from the Kenya Revenue Authority.

**VALID CODE FORMATS:**
- Level 1: 99000000
- Level 2: 99010000, 99020000
- Level 3: Codes starting with 99011000, 99011100, 99012000, 99013000, 99021000, or 8-digit codes from 10121600 to 95141600
- Level 4: Specific 8-digit codes under the Level 3 categories

**TAX TYPE CODES:**
- VAT_EXEMPT - For items matching codes under 99011000, 99011100, or 99021000
- VAT_ZERO - For items matching codes under 99012000
- VAT_STANDARD - For most other goods and services

**CLASSIFICATION RULES:**
1. Analyze item_name, description, and item_group
2. Find the semantically closest match from the official GitHub list
3. You must be able to verify the code exists in the official list
4. If uncertain, use the most specific Level 3 code available
5. NEVER return a code you cannot verify from the source

**ITEM DATA:**
{json.dumps(item_payload, indent=2)}

**RETURN ONLY VALID JSON - NO EXTRA TEXT:**
{{
    "predicted_code": "8-digit code from official list only",
    "predicted_name": "Official classification name from the list",
    "tax_type_code": "VAT_EXEMPT or VAT_ZERO or VAT_STANDARD",
    "confidence": 0,
    "reasoning": "Brief explanation of match",
    "alternative_codes": []
}}
"""

        if provider == "Google":
            return self.call_gemini(
                model_id=model_id,
                prompt=prompt,
            )

        api_key = self.settings.get_password("classification_api_key")

        if not api_key:
            frappe.throw(_("Missing AI API Key"))

        if provider in [
            "OpenAI",
            "DeepSeek",
            "Grok",
        ]:
            base_urls = {
                "OpenAI": "https://api.openai.com/v1",
                "DeepSeek": "https://api.deepseek.com",
                "Grok": "https://api.x.ai/v1",
            }

            return self.call_openai_compatible(
                api_key=api_key,
                model_id=model_id,
                prompt=prompt,
                base_url=base_urls.get(provider),
            )

        if provider == "Anthropic":
            return self.call_anthropic(
                api_key=api_key,
                model_id=model_id,
                prompt=prompt,
            )

        frappe.throw(_("Unsupported AI Provider"))

    def call_gemini(
        self,
        model_id,
        prompt,
    ):
        try:
            if self.settings.google_provider == "Google AI Studio":
                from google import genai

                api_key = self.settings.get_password("classification_api_key")

                if not api_key:
                    frappe.throw(_("Missing Google AI Studio API Key"))

                client = genai.Client(
                    api_key=api_key,
                )

                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                )

                if not response:
                    frappe.throw(_("Empty Gemini response"))

                text = getattr(
                    response,
                    "text",
                    None,
                )

                if not text:
                    frappe.throw(_("Gemini returned empty text"))

                return self.parse_json(text)

            elif self.settings.google_provider == "Vertex AI":
                import vertexai
                from google.oauth2 import service_account
                from vertexai.generative_models import GenerativeModel

                if not self.settings.gcp_service_account_key:
                    frappe.throw(_("Missing GCP Service Account Key"))

                key_info = json.loads(self.settings.gcp_service_account_key)

                credentials = service_account.Credentials.from_service_account_info(
                    key_info
                )

                vertexai.init(
                    project=self.settings.gcp_project_id,
                    location=self.settings.gcp_location or "us-central1",
                    credentials=credentials,
                )

                model = GenerativeModel(model_id)

                response = model.generate_content(prompt)

                if not response:
                    frappe.throw(_("Empty Vertex AI response"))

                text = getattr(
                    response,
                    "text",
                    None,
                )

                if not text:
                    frappe.throw(_("Vertex AI returned empty text"))

                return self.parse_json(text)

        except Exception as e:
            error = frappe.get_traceback()

            frappe.log_error(
                title="Google AI Classification Error",
                message=error,
            )

            if "429" in str(e):
                frappe.throw(
                    _(
                        "Google AI quota exceeded. Please upgrade billing, change credentials, or switch AI provider."
                    )
                )

            frappe.throw(_("Google AI request failed: {0}").format(str(e)))

    def call_openai_compatible(
        self,
        api_key,
        model_id,
        prompt,
        base_url,
    ):
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": model_id,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            }

            response = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )

            response.raise_for_status()

            data = response.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content")

            if not content:
                frappe.throw(_("AI returned empty response"))

            return self.parse_json(content)

        except Exception:
            error = frappe.get_traceback()

            frappe.log_error(
                title="OpenAI Compatible Classification Error",
                message=error,
            )

            frappe.throw(_("AI classification request failed."))

    def call_anthropic(
        self,
        api_key,
        model_id,
        prompt,
    ):
        try:
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }

            payload = {
                "model": model_id,
                "max_tokens": 2048,
                "temperature": 0.1,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            }

            response = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=120,
            )

            response.raise_for_status()

            result = response.json()

            content = result.get("content", [{}])[0].get("text")

            if not content:
                frappe.throw(_("Anthropic returned empty response"))

            return self.parse_json(content)

        except Exception:
            error = frappe.get_traceback()

            frappe.log_error(
                title="Anthropic Classification Error",
                message=error,
            )

            frappe.throw(_("Anthropic classification request failed."))

    def parse_json(self, text):
        clean = re.sub(
            r"```json|```",
            "",
            text,
        ).strip()

        try:
            return json.loads(clean)

        except Exception:
            pass

        try:
            match = re.search(
                r"({.*})",
                clean,
                re.DOTALL,
            )

            if match:
                return json.loads(match.group(1))

        except Exception:
            pass

        frappe.log_error(
            title="AI Invalid JSON",
            message=clean,
        )

        frappe.throw(_("AI returned invalid JSON response."))

    def normalize_prediction(self, result):
        predicted_code = (result.get("predicted_code") or "").strip()

        if not predicted_code:
            return {
                "success": False,
                "message": _("No predicted code returned."),
            }

        return {
            "success": True,
            "classification": predicted_code,
            "classification_code": predicted_code,
            "classification_name": result.get("predicted_name", ""),
            "tax_type_code": result.get("tax_type_code", ""),
            "confidence": result.get("confidence", 0),
            "reasoning": result.get("reasoning"),
            "alternative_codes": result.get("alternative_codes", []),
            "raw_response": result,
        }

    def save_prediction(self, prediction):
        if not prediction.get("success"):
            return

        json_field_name = "custom_ai_classification_data"
        current_data_str = self.item.get(json_field_name)

        try:
            current_data = (
                json.loads(current_data_str)
                if current_data_str and isinstance(current_data_str, str)
                else (current_data_str or {})
            )
        except Exception:
            current_data = {}

        current_data.update(
            {
                "classification_code": prediction.get("classification_code"),
                "confidence": prediction.get("confidence", 0),
                "reasoning": prediction.get("reasoning"),
            }
        )

        self.item.db_set(
            json_field_name,
            json.dumps(current_data),
            update_modified=False,
        )

        confidence = prediction.get("confidence", 0)
        if self.settings.auto_classify_items and confidence >= 95:
            if frappe.db.has_column("Item", "custom_item_classification"):
                self.item.db_set(
                    "custom_item_classification",
                    prediction.get("classification_code"),
                    update_modified=False,
                )

            if prediction.get("tax_type_code") and frappe.db.has_column(
                "Item", "custom_taxation_type"
            ):
                self.item.db_set(
                    "custom_taxation_type",
                    prediction.get("tax_type_code"),
                    update_modified=False,
                )

    def default_prompt(self):
        return """
You are an expert Kenya KRA eTIMS product classifier.

You have internal knowledge of the complete official KRA classification codes from:
https://github.com/muruthigitau/eTims-Classification-Codes#readme

You understand ERPNext, inventory management, Kenyan VAT taxation, and business semantics across all sectors.

CRITICAL RULE - NO CODE INVENTION:
You must NEVER generate, invent, or create any classification code.
You must ONLY return codes that exist in the official GitHub repository list.
Every code you return must be verifiable from that source.

Your task is to match ERPNext items to existing KRA classification codes only.
"""


@frappe.whitelist()
def classify_item(
    item,
    settings_name,
):
    classifier = ETimsItemClassifier(
        item_name=item,
        settings_name=settings_name,
    )

    return classifier.classify()
