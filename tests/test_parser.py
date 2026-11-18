from app.scraper.parser import (
    latest_benchmark,
    parse_benchmarks,
    parse_camera,
    parse_charging,
    parse_memory,
    parse_phone_page,
    parse_prices,
)

PAGE = """
<html><body>
<h1 class="specs-phone-name-title">Samsung Galaxy Test</h1>
<div class="specs-photo-main"><a><img src="https://example.com/p.jpg"></a></div>
<div id="specs-list">
<table><tr><th rowspan="2">Launch</th><td class="ttl">Announced</td><td class="nfo" data-spec="year">2023, February 01</td></tr>
<tr><td class="ttl">Status</td><td class="nfo" data-spec="status">Available. Released 2023, February 17</td></tr></table>
<table><tr><th>Body</th><td class="ttl">Weight</td><td class="nfo" data-spec="weight">168 g (5.93 oz)</td></tr>
<tr><td class="ttl">&nbsp;</td><td class="nfo" data-spec="bodyother">IP68 dust tight and water resistant</td></tr></table>
<table><tr><th>Display</th><td class="ttl">Type</td><td class="nfo" data-spec="displaytype">Dynamic AMOLED 2X, 120Hz, 1750 nits (peak)</td></tr>
<tr><td class="ttl">Size</td><td class="nfo" data-spec="displaysize">6.1 inches, 90.1 cm<sup>2</sup></td></tr>
<tr><td class="ttl">Resolution</td><td class="nfo" data-spec="displayresolution">1080 x 2340 pixels (~425 ppi density)</td></tr></table>
<table><tr><th>Memory</th><td class="ttl">Internal</td><td class="nfo" data-spec="internalmemory">128GB 8GB RAM, 256GB 8GB RAM, 1TB 12GB RAM</td></tr></table>
<table><tr><th>Main Camera</th><td class="ttl">Triple</td><td class="nfo" data-spec="cam1modules">50 MP, f/1.8 (wide)<br>10 MP (telephoto), 3x optical zoom<br>12 MP (ultrawide)</td></tr></table>
<table><tr><th>Battery</th><td class="ttl">Type</td><td class="nfo" data-spec="batdescription1">Li-Ion 3900 mAh</td></tr>
<tr><td class="ttl">Charging</td><td class="nfo">25W wired<br>15W wireless (Qi)</td></tr></table>
<table><tr><th>Misc</th><td class="ttl">Price</td><td class="nfo" data-spec="price"><a>$&thinsp;230.61 / &euro;&thinsp;276.98</a></td></tr></table>
<table><tr><th>Our Tests</th><td class="ttl">Performance</td><td class="nfo" data-spec="tbench">AnTuTu: 745496 (v8), 881428 (v9)<br>GeekBench: 4950 (v5.1)</td></tr>
<tr><td class="ttl">Battery (old)</td><td class="nfo" data-spec="batlife">Endurance rating 101h</td></tr></table>
</div></body></html>
"""


def test_parse_phone_page():
    r = parse_phone_page(PAGE, "test-1", "https://example.com/test-1.php")
    assert r["name"] == "Samsung Galaxy Test"
    assert r["display_size_in"] == 6.1
    assert r["refresh_rate_hz"] == 120 and r["ppi"] == 425 and r["peak_brightness_nits"] == 1750
    assert r["ram_gb"] == 12 and r["storage_options"] == "128GB/256GB/1TB" and r["max_storage_gb"] == 1024
    assert r["main_camera_mp"] == 50 and r["main_camera_count"] == 3 and r["optical_zoom_x"] == 3
    assert r["battery_mah"] == 3900 and r["charging_wired_w"] == 25 and r["charging_wireless_w"] == 15
    assert r["battery_endurance_h"] == 101
    assert r["antutu_score"] == 881428 and r["antutu_version"] == "v9"
    assert r["geekbench_score"] == 4950
    assert r["price_usd"] == 230.61
    assert r["weight_g"] == 168 and r["ip_rating"] == "IP68" and r["release_year"] == 2023
    cams = [s for s in r["specifications"] if s["category"] == "Main Camera"][0]
    assert cams["value"].count("\n") == 2  # <br>-separated modules preserved


def test_parse_prices_formats():
    assert parse_prices("$ 1,199.99 / € 999.00") == [
        {"currency": "USD", "amount": 1199.99}, {"currency": "EUR", "amount": 999.0}]
    assert parse_prices("About 800 EUR") == [{"currency": "EUR", "amount": 800.0}]
    assert parse_prices(None) == []


def test_field_parsers():
    assert parse_memory("256GB 12GB RAM, 512GB 12GB RAM") == (12.0, "256GB/512GB", 512)
    assert parse_camera("200 MP (wide)\n10 MP, 10x optical zoom")[::2] == (200.0, 10.0)
    assert parse_charging("45W wired, PD3.0\n15W wireless") == (45.0, 15.0)


def test_benchmarks_new_battery_format():
    b = parse_benchmarks([{"name": "Battery", "value": "Active use score 11:27h"}])
    assert b[0]["score"] == 11.45
    multi = parse_benchmarks([{"name": "Performance", "value": "AnTuTu: 1 (v9), 2 (v10)"}])
    assert latest_benchmark(multi, "antutu")["version"] == "v10"
