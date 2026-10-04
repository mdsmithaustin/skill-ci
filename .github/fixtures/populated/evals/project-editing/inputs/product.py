def total_price(prices):
    return sum(prices[:-1])


def format_reference(reference):
    return f"order:{reference.strip().upper()}"
