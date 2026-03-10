import categorize_wp_posts as cwp
import wp_agent


EXPECTED_MODELS = {
    'gpt-5.4': {'in_per_m': 2.50, 'out_per_m': 20.00},
    'gpt-5-pro': {'in_per_m': 15.00, 'out_per_m': 120.00},
    'gpt-4.1': {'in_per_m': 2.00, 'out_per_m': 8.00},
    'gpt-4.1-mini': {'in_per_m': 0.40, 'out_per_m': 1.60},
    'gpt-4.1-nano': {'in_per_m': 0.10, 'out_per_m': 0.40},
}


def test_wp_agent_price_table_includes_latest_models():
    for model, expected in EXPECTED_MODELS.items():
        assert wp_agent.PRICE_TABLE_DEFAULT.get(model) == expected


def test_categorize_price_table_includes_latest_models():
    for model, expected in EXPECTED_MODELS.items():
        assert cwp.PRICE_TABLE_DEFAULT.get(model) == expected
