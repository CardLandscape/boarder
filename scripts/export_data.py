import json
import os

os.makedirs('data', exist_ok=True)

# Export ISO countries via pycountry
try:
    import pycountry
    countries = [{'alpha_3': c.alpha_3, 'name': c.name} for c in pycountry.countries]
    with open('data/iso_countries.json', 'w', encoding='utf-8') as f:
        json.dump(countries, f, ensure_ascii=False, indent=2)
    print('ISO_EXPORT', len(countries))
except Exception as e:
    print('ISO_EXPORT_ERROR', e)

# Export IATA codes via airportsdata
try:
    from airportsdata import load
    ap = load('IATA')
    by_city = {}
    for code, info in ap.items():
        city = (info.get('city') or '').strip().lower()
        country = (info.get('country') or '').strip().lower()
        if city:
            key = (city, country)
        else:
            key = (code.lower(), country)
        by_city.setdefault(key, []).append((code, info))

    def is_city_code_record(record):
        name = (record.get('name') or '').strip().lower()
        city = (record.get('city') or '').strip().lower()
        if not city:
            return False
        if name == city:
            return True
        if name.startswith(city) and 'airport' not in name:
            return True
        return False

    iatas = []
    for entries in by_city.values():
        if len(entries) > 1:
            city_code = next((code for code, info in entries if is_city_code_record(info)), None)
            if city_code:
                iatas.append(city_code)
                continue
        iatas.extend([code for code, _ in entries])

    iatas = sorted(set(iatas))
    with open('data/iata_codes.json', 'w', encoding='utf-8') as f:
        json.dump(iatas, f, ensure_ascii=False, indent=2)
    print('IATA_EXPORT', len(iatas))
except Exception as e:
    print('IATA_EXPORT_ERROR', e)
