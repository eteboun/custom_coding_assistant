from decimal import Decimal

from .schema import ModelData, TokenUsage

def calculate_cost_usd(usage: TokenUsage, model: ModelData) -> Decimal:
    pricing = model.pricing
    input_rate = Decimal(str(pricing.input))
    output_rate = Decimal(str(pricing.output))
    cached_rate = Decimal(str(
        pricing.input if pricing.cached_input is None else pricing.cached_input
    ))

    rules = model.pricing_rules
    if (
        rules is not None
        and rules.long_context_threshold is not None
        and usage.input_tokens > rules.long_context_threshold
    ):
        if rules.above_threshold is not None:
            higher_input = Decimal(str(rules.above_threshold.input))
            cached_rate *= higher_input / input_rate
            input_rate = higher_input
            output_rate = Decimal(str(rules.above_threshold.output))
        else:
            if rules.above_threshold_input_multiplier is not None:
                multiplier = Decimal(str(rules.above_threshold_input_multiplier))
                input_rate *= multiplier
                cached_rate *= multiplier
            if rules.above_threshold_output_multiplier is not None:
                output_rate *= Decimal(str(rules.above_threshold_output_multiplier))

    cached = usage.cached_input_tokens or 0
    if cached > usage.input_tokens:
        raise ValueError("Cached input tokens exceed input tokens")

    return (
        (usage.input_tokens - cached) * input_rate
        + cached * cached_rate
        + usage.output_tokens * output_rate
    ) / Decimal(1_000_000)
