from botasaurus.browser import browser, Driver, AsyncQueueResult
from botasaurus.request import request, Request
from botasaurus.lang import Lang
import json
import re
from fuzzywuzzy import fuzz
import csv
import time
from urllib.parse import unquote
from shapely.geometry import Point, shape



def load_pasaman_polygon(geojson_path):
    with open(geojson_path) as f:
        geojson = json.load(f)

    return shape(geojson['features'][0]['geometry'])

pasaman_polygon = load_pasaman_polygon('13.08_Pasaman.geojson')

def filter_check_pasaman(places, pasaman_polygon):
    print("=== CEK USAHA DI KABUPATEN PASAMAN ===\n")

    result = []

    for name, coord in places:
        lat = float(coord['lat'])
        lon = float(coord['long'])

        point = Point(lon, lat)

        # Gunakan covers agar titik di batas tetap dianggap masuk
        is_in_pasaman = pasaman_polygon.covers(point)

        if is_in_pasaman:
            result.append([name, coord])

        print(f"Nama Usaha : {name}")
        print(f"Koordinat  : lat={lat}, long={lon}")
        print(f"Status     : {'DI PASAMAN ✅' if is_in_pasaman else 'BUKAN PASAMAN ❌'}")
        print("-" * 50)

    return result






def find_best_match(input_name, places, min_ratio=70, min_partial=85):
    best_match = None
    best_score = 0

    nama_usaha = re.sub(r'\s*kabupaten\s+pasaman\s*', ' ', input_name, flags=re.IGNORECASE).strip()

    for place_name, coord in places:
        ratio_score = fuzz.ratio(nama_usaha.lower(), place_name.lower())
        partial_score = fuzz.partial_ratio(nama_usaha.lower(), place_name.lower())

        print(f"\nUsaha {place_name} => Ratio : {ratio_score}, Partial ratio: {partial_score}")

        # Ambil skor tertinggi dari dua metode
        final_score = max(ratio_score, partial_score)

        if (
            (ratio_score >= min_ratio and partial_score >= min_partial) and final_score > best_score
        ):
            best_score = final_score
            best_match = {
                'name': place_name,
                'coordinates': coord,
                'ratio': ratio_score,
                'status': 'Ditemukan',
                'partial_ratio': partial_score,
                'score': final_score
            }

    return best_match


def extract_place_and_coordinates(urls):
    results = []

    for url in urls:
        # Decode URL (%2F, %60, dll)
        decoded_url = unquote(url)

        # 1. Ekstrak nama tempat
        name_match = re.search(r'/place/([^/]+)/data', decoded_url)
        name = name_match.group(1).replace('+', ' ') if name_match else None

        # 2. Ekstrak koordinat
        lat_match = re.search(r'!3d([-0-9.]+)', decoded_url)
        long_match = re.search(r'!4d([-0-9.]+)', decoded_url)

        lat = lat_match.group(1) if lat_match else None
        long = long_match.group(1) if long_match else None

        results.append([
            name,
            {
                'lat': lat,
                'long': long
            }
        ])

    return results




def extract_lat_long(google_maps_url: str):
    """
    Mengambil latitude dan longitude dari URL Google Maps.
    Return: (lat, long) sebagai float
    """
    pattern = r'@(-?\d+\.\d+),(-?\d+\.\d+)'
    match = re.search(pattern, google_maps_url)

    if not match:
        return None, None

    lat = float(match.group(1))
    lon = float(match.group(2))
    return lat, lon


def extract_list_data(html):
    try:
        # Indeks baru untuk nama dan alamat
        data_string = json.loads(
            html.split(";window.APP_INITIALIZATION_STATE=")[1].split(";window.APP_FLAGS")[0]
        )[9][0]

        print(f"=> Data String : {data_string}")

        if not data_string or '·' not in data_string:
            return None, None

        # Pisahkan nama dan alamat
        parts = data_string.split('·', 1)
        compared_name = parts[0].strip()
        address_part = parts[1].strip() if len(parts) > 1 else ""

        # Ekstrak Kabupaten/Kota dari alamat
        location_match = re.search(r'(Kabupaten|Kota)\s+([^,]+)', address_part, re.IGNORECASE)
        compared_location = ""
        if location_match:
            # Ambil "Kabupaten/Kota NamaLokasi"
            compared_location = f"{location_match.group(1).strip()} {location_match.group(2).strip()}"
        
        return compared_name, compared_location

    except Exception as e:
        # print(f"Debug extract_list_data error: {e}") # Opsional: uncomment untuk debug
        return None, None

# Fungsi untuk melakukan validasi kesamaan nama usaha
def validation(business_name, compared_name, business_location, compared_location):
    if not business_name or not compared_name:
        # Validasi nama gagal jika salah satu kosong
        return False

    # --- Validasi Nama (Tahap 1) ---
    # Cek fuzzy ratio
    ratio = fuzz.ratio(business_name.lower(), compared_name.lower())
    partial_ratio = fuzz.partial_ratio(business_name.lower(), compared_name.lower())

    print(f"\nratio: {ratio}\npartial_ratio: {partial_ratio}")
    
    name_match = (ratio >= 70 or partial_ratio >= 80)

    if not name_match:
        # Jika nama tidak cocok, langsung return False
        return False

    # --- Validasi Lokasi (Tahap 2 - Hanya jika nama cocok) ---
    if not business_location or not compared_location:
        # Jika salah satu data lokasi tidak ada, anggap lokasi tidak cocok (atau bisa diubah jadi True jika hanya nama yg penting)
        print(f"Peringatan: Data lokasi tidak lengkap untuk validasi ({business_name} vs {compared_name}). BusinessLoc: '{business_location}', ComparedLoc: '{compared_location}'")
        return False 

    # Hapus "Kabupaten"/"Kota" untuk perbandingan fuzzy lokasi yang lebih baik
    clean_business_loc = re.sub(r'^(Kabupaten|Kota)\s+', '', business_location, flags=re.IGNORECASE).strip()
    clean_compared_loc = re.sub(r'^(Kabupaten|Kota)\s+', '', compared_location, flags=re.IGNORECASE).strip()

    if not clean_business_loc or not clean_compared_loc:
         print(f"Peringatan: Data lokasi bersih tidak lengkap untuk validasi ({business_name} vs {compared_name}). CleanBusinessLoc: '{clean_business_loc}', CleanComparedLoc: '{clean_compared_loc}'")
         return False # Lokasi tidak bisa dibandingkan

    # Cek fuzzy ratio lokasi
    loc_ratio = fuzz.ratio(clean_business_loc.lower(), clean_compared_loc.lower())
    loc_partial_ratio = fuzz.partial_ratio(clean_business_loc.lower(), clean_compared_loc.lower())

    location_match = (loc_ratio >= 75 or loc_partial_ratio >= 90)

    # Hanya return True jika NAMA dan LOKASI cocok
    return location_match

# Ekstrak nama usaha dari query
def extract_business_name(query):
    # Ekstrak nama dan lokasi lengkap ("Kabupaten X" / "Kota Y")
    match_kab = re.search(r'(.+?)\s+(Kabupaten\s+.+)', query, re.IGNORECASE)
    match_kota = re.search(r'(.+?)\s+(Kota\s+.+)', query, re.IGNORECASE)
    
    if match_kab:
        business_name = match_kab.group(1).strip()
        location = match_kab.group(2).strip()
        return business_name, location
    elif match_kota:
        business_name = match_kota.group(1).strip()
        location = match_kota.group(2).strip()
        return business_name, location
    else:
        # Jika tidak ada pemisah Kabupaten/Kota, anggap seluruh query adalah nama
        return query, ""



@browser(block_images_and_css=True,
         #headless=True,
         output=None,
         wait_for_complete_page_load=True,
         lang=Lang.Indonesian,
         cache=True)
def crosscheck_business(driver: Driver, query):
    # Dapatkan nama dan lokasi dari query awal
    business_name, business_location = extract_business_name(query) 
    search_url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    
    try:
        driver.google_get(search_url, accept_google_cookies=True)
        
        compared_name = ""
        compared_location = ""
        is_list_view = False

        # Coba ambil H1 dulu untuk deteksi jenis halaman
        try:
            h1_text = driver.get_text("h1")
            print(f"=> h1 ada: {h1_text}")
            if h1_text and ("hasil" in h1_text.lower() or "results" in h1_text.lower()):
                is_list_view = True
            else:
                 compared_name = h1_text # Jika bukan list view, H1 adalah nama pembanding
        except Exception:
            # Jika H1 tidak ada, ini list view
             is_list_view = True 

        # --- Proses Halaman List View ---
        if is_list_view:
            links = driver.get_all_links('[role="feed"] > div > div > a')
            links = links[:5]

            # print(links)
            
            if not links:
                return (business_name, query, False, None, None)
            

            places = extract_place_and_coordinates(links)
            print(places)

            filter_pasaman = filter_check_pasaman(places, pasaman_polygon)

            print(filter_pasaman)
            

            print("\n\t===> Find the best match:")
            print("\n===> Find the best match:")
            best_match = find_best_match(business_name, filter_pasaman)
            print(best_match)


            # return
            
            # Proses hasil list view yang sekarang (link, is_found)
            # final_found_status = False
            # if isinstance(results, list) and len(results) > 0:
            #      if isinstance(results[0], tuple): # Jika hasilnya list of tuples (link, is_found)
            #           for _link, is_found in results:
            #                if is_found:
            #                     final_found_status = True
            #                     break
            #      else: # Jika hasilnya flat list [link1, found1, link2, found2, ...]
            #           for i in range(0, len(results), 2):
            #                if i+1 < len(results):
            #                     is_found = results[i+1]
            #                     if is_found:
            #                          final_found_status = True
            #                          break
            # time.sleep(3)
            # return (business_name, query, final_found_status, None, None)
            if best_match :
                return (business_name, query, True, best_match['coordinates']['lat'], best_match['coordinates']['long'])
            return (business_name, query, False, None, None)
        # --- Proses Halaman Profil ---
        else:
            # Ambil lokasi pembanding dari div
            try:
                # Selector CSS untuk div alamat
                location_selector = "div.Io6YTe.fontBodyMedium.kR99db.fdkmkc" 
                address_text = driver.get_text(location_selector)

                print(f"\n=> address_text : {address_text}")
                
                # Ekstrak Kabupaten/Kota dari alamat
                location_match = re.search(r'([^,]+?)\s+(?:Regency|City)', address_text, re.IGNORECASE)

                if not location_match:
                    location_match = re.search(r'\b(?:Kabupaten|Kota)\s+([^,]+)', address_text, re.IGNORECASE)

                print(f"\n=> location_match : {location_match}")

                if location_match:
                    # group(1) adalah bagian nama kabupatennya
                    kabupaten_name = "Kabupaten " + location_match.group(1).strip()
                    print(f"\nHasil: {kabupaten_name}\n")
                    compared_location = kabupaten_name
                else:
                    print("Tidak ditemukan")

                # if location_match:
                #     compared_location = f"{location_match.group(1).strip()} {location_match.group(2).strip()}"
            except Exception:
                 # Jika div lokasi tidak ditemukan, biarkan compared_location kosong
                 print(f"Peringatan: Div lokasi tidak ditemukan untuk {query}")
                #  compared_location = "" 

            # Lakukan validasi lengkap (nama & lokasi)
            is_found = validation(business_name, compared_name, business_location, compared_location)

            # BARIS FUNGSI UNTUK MENDAPATKAN LINK

            # Batas maksimal menunggu (misal: 10 detik)
            max_wait_seconds = 10 
            waited = 0
            
            # Loop akan berjalan selama URL masih salah DAN waktu tunggu belum habis
            while "https://www.google.com/maps/search" in driver.current_url and waited < max_wait_seconds:
                time.sleep(1)
                waited += 1
                # Opsional: Print status untuk debugging
                print(f"Menunggu redirect URL... ({waited}s)")
            final_url = driver.current_url

            print(f"\n=>URL : {final_url}\n")

            print(f"\nbusiness_name : {business_name}\nquery : {query}\nis_found : {is_found}")
            print('\n==== END ITEM ====\n\n')


            lat, long = extract_lat_long(final_url)

            return (business_name, query, is_found, lat, long)
            
    except Exception as e:
        print(f"Error processing {query}: {e}")
        return (business_name, query, False, None, None)

def load_businesses_from_file(file_path):
    businesses = []
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line = line.strip()
                if line:
                    # Membersihkan karakter khusus <>()
                    line = re.sub(r'[<>()]', '', line)
                    
                    # Memperbaiki format badan hukum (PT/CV) yang di akhir nama
                    # Pola: "NAMA, (kata) LOKASI" -> "(kata) NAMA LOKASI"
                    matches = re.match(r'(.+?),\s*([^,]+?)\s+(Kabupaten|Kota)\s+(.+)', line, re.IGNORECASE)
                    if matches:
                        nama = matches.group(1).strip()
                        kata = matches.group(2).strip().upper()
                        tipe_lokasi = matches.group(3).strip()
                        lokasi = matches.group(4).strip()
                        line = f"{kata} {nama} {tipe_lokasi} {lokasi}"
                    
                    businesses.append(line)
        return businesses
    except Exception as e:
        print(f"Error loading businesses: {e}")
        return []

def save_results_to_csv(results, filename="hasil_crosscheck.csv"):
    with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Nama Usaha di Maps', 'query', 'Hasil Crosscheck', 'Lattitude', 'Longitude'])
        
        # Loop melalui data array
        for name_maps, query, found, lat, lon in results:
            status = "Ditemukan" if found else "Tidak Ditemukan"
            # Menulis baris data
            writer.writerow([name_maps, query, status, lat, lon])
    
    print(f"Hasil crosscheck disimpan di {filename}")

if __name__ == "__main__":
    # Baca data usaha dari file
    businesses = load_businesses_from_file("bisnis.txt")
    results = []
    
    # Proses setiap usaha
    for query in businesses:
        # Panggil crosscheck_business untuk setiap query
        result = crosscheck_business(query) 
        results.append(result)

        # print(f"\n\n=== RESULT : {result}")
        
        # Output log 
        # Unpack hasil tuple (business_name, query, found)
        # business_name, _, found = result 
        # status_code = "1" if found else "0"
        # # Ekstrak lokasi dari query asli untuk log
        # _, business_location_log = extract_business_name(query)
        # print(f"{status_code}   {business_name} {business_location_log}") 
    
    # Simpan hasil ke CSV
    save_results_to_csv(results)
    
    # Tampilkan ringkasan
    found_count = sum(1 for _, _, found, _, _ in results if found)

    total = len(results)
    
    print(f"Selesai! Total usaha divalidasi: {total}")
    print(f"Result:\n{results}")
    print(f"Usaha ditemukan: {found_count}")
    print(f"Usaha tidak ditemukan: {total - found_count}")