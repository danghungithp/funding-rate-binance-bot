import json

with open('premiumIndex.json', 'r') as f:
    data = json.load(f)

# Lọc funding rate dương, sắp xếp giảm dần, lấy top 10
positive = [x for x in data if float(x['lastFundingRate']) > 0]
positive_sorted = sorted(positive, key=lambda x: float(x['lastFundingRate']), reverse=True)
top10 = [x['symbol'] for x in positive_sorted[:10]]
print(top10)
