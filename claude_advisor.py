"""
Claude API integration — the brain of the expense tracker.
Four roles: Transaction Extractor, Financial Advisor, Forecast Analyst, Report Writer.
"""

import json
import os
import re
import time
from typing import Optional

import anthropic

import config
from prompts.extraction import build_extraction_prompt, build_checking_extraction_prompt
from prompts.advisor import build_advisor_prompt, build_quick_analysis_prompt
from prompts.forecast import build_forecast_prompt, build_scenario_prompt


class ClaudeAdvisor:
    """Unified interface for all Claude API interactions."""

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError(
                "ANTHROPIC_API_KEY not set. Provide it via environment variable or in Settings."
            )
        self.client = anthropic.Anthropic(api_key=key)
        self.model = config.ANTHROPIC_MODEL
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    # ── Internal helpers ──────────────────────────────────────────────────

    def _call(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Unified API call with retry logic."""
        for attempt in range(3):
            try:
                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=messages,
                )
                self.total_input_tokens += response.usage.input_tokens
                self.total_output_tokens += response.usage.output_tokens
                return response.content[0].text
            except anthropic.RateLimitError:
                wait = 2 ** attempt
                time.sleep(wait)
            except anthropic.APIError as e:
                if attempt == 2:
                    raise
                time.sleep(1)
        raise RuntimeError("Claude API call failed after 3 attempts")

    def _parse_json(self, text: str) -> dict:
        """Extract JSON from Claude's response, handling markdown fences."""
        # Strip markdown code fences if present
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                return json.loads(match.group())
            raise ValueError(f"Could not parse JSON from Claude response:\n{text[:500]}")

    # ── Role 1: Transaction Extractor ─────────────────────────────────────

    def extract_transactions(
        self,
        raw_text: str,
        tables: list,
        account_hint: Optional[str] = None,
        existing_periods: Optional[list[dict]] = None,
        is_checking: bool = False,
        categories: Optional[list[str]] = None,
    ) -> dict:
        """Extract and categorize all transactions from a statement."""
        existing = existing_periods or []

        if is_checking:
            system_prompt = build_checking_extraction_prompt(existing)
        else:
            system_prompt = build_extraction_prompt(account_hint, existing, categories=categories)

        # Build the user message with the statement content
        user_content = f"Here is the bank statement to extract:\n\n{raw_text}"
        if tables:
            user_content += f"\n\nEXTRACTED TABLES:\n{json.dumps(tables[:10], indent=1)}"

        messages = [{"role": "user", "content": user_content}]

        response_text = self._call(
            system=system_prompt,
            messages=messages,
            max_tokens=config.MAX_TOKENS_EXTRACTION,
            temperature=0.1,
        )

        return self._parse_json(response_text)

    # ── Role 2: Financial Advisor ─────────────────────────────────────────

    def get_advisor_response(
        self,
        user_message: str,
        conversation_history: list[dict],
        financial_context: dict,
        tactical_context: dict = None,
    ) -> dict:
        """Get advice from Claude as a personal financial advisor."""
        system_prompt = build_advisor_prompt(financial_context, tactical_context)

        # Build messages array from history + new message
        messages = []
        for msg in conversation_history[-20:]:  # Keep last 20 messages for context
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        response_text = self._call(
            system=system_prompt,
            messages=messages,
            max_tokens=config.MAX_TOKENS_ADVISOR,
            temperature=0.3,
        )

        # Try to parse structured response, fall back to plain text
        try:
            result = self._parse_json(response_text)
            if "response" not in result:
                result = {"response": response_text, "follow_up_questions": [], "alerts": [], "suggested_actions": []}
        except (ValueError, json.JSONDecodeError):
            result = {
                "response": response_text,
                "follow_up_questions": [],
                "alerts": [],
                "suggested_actions": [],
            }

        return result

    def get_quick_analysis(self, extraction_result: dict) -> str:
        """Quick analysis of a newly uploaded statement."""
        system_prompt = build_quick_analysis_prompt()
        messages = [
            {
                "role": "user",
                "content": f"Analyze this statement extraction:\n\n{json.dumps(extraction_result, indent=2)[:8000]}",
            }
        ]
        return self._call(system=system_prompt, messages=messages, max_tokens=1024, temperature=0.3)

    def generate_gap_closer(self, gap: float, discretionary_spent: float, discretionary_budget: float,
                            days_left: int, savings_target: int, transactions_text: str,
                            category_summary: str) -> dict:
        """Generate top 3 actions to close the savings gap."""
        from prompts.advisor import build_gap_closer_prompt
        system_prompt = build_gap_closer_prompt(
            gap, discretionary_spent, discretionary_budget,
            days_left, savings_target, transactions_text, category_summary,
        )
        messages = [{"role": "user", "content": "Analyze my spending and give me the top 3 actions to close my gap."}]
        response_text = self._call(system=system_prompt, messages=messages, max_tokens=1024, temperature=0.2)
        return self._parse_json(response_text)

    def generate_coach_response(self, system_prompt: str, max_tokens: int = 1024) -> dict:
        """Generic coach response — prompt comes from coach_prompts.py."""
        messages = [{"role": "user", "content": "Analyze and respond based on the context provided."}]
        response_text = self._call(system=system_prompt, messages=messages, max_tokens=max_tokens, temperature=0.3)
        return self._parse_json(response_text)

    def generate_preventive_actions(self, categories_data: list[dict]) -> list[dict]:
        """Claude analyzes Prophet forecasts + historical trends to generate
        preventive spending actions per category."""
        from prompts.advisor import build_preventive_actions_prompt

        system_prompt = build_preventive_actions_prompt(categories_data)
        messages = [
            {"role": "user", "content": "Generate preventive actions for each category based on the forecast data."}
        ]
        response_text = self._call(system=system_prompt, messages=messages, max_tokens=2048, temperature=0.3)
        try:
            result = self._parse_json(response_text)
            if isinstance(result, list):
                return result
            return [result]
        except (ValueError, json.JSONDecodeError):
            return []

    def get_welcome_message(self, financial_context: dict) -> str:
        """Generate a proactive welcome message based on current financial state."""
        system_prompt = build_advisor_prompt(financial_context)
        messages = [
            {
                "role": "user",
                "content": (
                    "I just opened the app. Give me a brief status update: "
                    "How are our finances looking? Any concerns? What should I focus on today? "
                    "Keep it to 3-4 sentences max, then ask one focused question."
                ),
            }
        ]
        return self._call(system=system_prompt, messages=messages, max_tokens=512, temperature=0.4)

    # ── Role 3: Forecast Analyst ──────────────────────────────────────────

    def generate_forecast(
        self,
        projection_summary: dict,
        historical_summary: dict,
    ) -> dict:
        """Claude interprets a numerical projection and adds narrative + recommendations."""
        system_prompt = build_forecast_prompt(projection_summary, historical_summary)
        messages = [
            {
                "role": "user",
                "content": "Please analyze this cash flow projection and provide your forecast assessment.",
            }
        ]

        response_text = self._call(
            system=system_prompt,
            messages=messages,
            max_tokens=config.MAX_TOKENS_FORECAST,
            temperature=0.3,
        )

        try:
            return self._parse_json(response_text)
        except (ValueError, json.JSONDecodeError):
            return {
                "narrative": response_text,
                "risk_factors": [],
                "recommendations": [],
                "milestones": [],
                "confidence": "medium",
                "data_gaps": [],
            }

    def analyze_scenario(
        self,
        base_summary: dict,
        scenario_summary: dict,
        adjustments: dict,
    ) -> str:
        """Claude compares a what-if scenario to the base case."""
        system_prompt = build_scenario_prompt(base_summary, scenario_summary, adjustments)
        messages = [
            {"role": "user", "content": "Please compare the scenario to the base case."}
        ]
        return self._call(system=system_prompt, messages=messages, max_tokens=1024, temperature=0.3)

    # ── Role 4: Report Writer ─────────────────────────────────────────────

    def generate_weekly_report(
        self,
        week_transactions: list[dict],
        monthly_context: dict,
        objective_progress: dict,
        alerts: list[dict],
        statistical_context: dict = None,
    ) -> dict:
        """Claude writes the weekly financial report using data-driven prompt."""
        from datetime import date
        from prompts.report import build_weekly_report_prompt
        import models

        today = date.today()

        # Read savings target from DB
        import database as _db
        import os as _os
        _db_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", config.DB_FILENAME)
        try:
            _conn = _db.get_connection(_db_path)
            savings_target = int(_db.get_setting(_conn, "monthly_savings_target", "1000"))
            _conn.close()
        except Exception:
            savings_target = 1000

        system_prompt = build_weekly_report_prompt(
            statistical_context=statistical_context,
            savings_target=savings_target,
        )

        context = {
            "week_transactions": week_transactions[:50],  # Limit for token budget
            "monthly_context": monthly_context,
            "objective_progress": objective_progress,
            "alerts": alerts,
            "family": config.FAMILY,
            "savings_levers": config.SAVINGS_LEVERS,
            "savings_target": savings_target,
        }

        messages = [
            {
                "role": "user",
                "content": f"Generate the weekly report based on this data:\n\n{json.dumps(context, indent=2, default=str)[:8000]}",
            }
        ]

        response_text = self._call(system=system_prompt, messages=messages, max_tokens=config.MAX_TOKENS_REPORT)

        try:
            return self._parse_json(response_text)
        except (ValueError, json.JSONDecodeError):
            return {
                "subject": "Weekly Budget Report",
                "html_body": f"<html><body><pre>{response_text}</pre></body></html>",
                "plain_text": response_text,
                "key_metrics": {},
                "action_items": [],
            }

    # ── Token usage tracking ──────────────────────────────────────────────

    def get_usage(self) -> dict:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "estimated_cost": round(
                self.total_input_tokens * 0.003 / 1000
                + self.total_output_tokens * 0.015 / 1000,
                4,
            ),
        }
