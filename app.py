# ==========================================
# BAGIAN IMPORT 
# ==========================================
import os
import io
import time
import uuid
import hmac
import hashlib
import calendar
import datetime
import base64
import pytz

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import extra_streamlit_components as stx
import geopy.distance
from PIL import Image
from streamlit_js_eval import get_geolocation
from dotenv import load_dotenv
from supabase import create_client, Client

# ==========================================
# FUNGSI UTILITAS AWAL (Sangat Ringan)
# ==========================================
def kompres_foto(image_bytes, quality=50, max_size=(400, 400)):
    """Fungsi kompresi ekstrem untuk menghemat Egress dan Storage"""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.thumbnail(max_size)
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality, optimize=True)
        return output.getvalue()
    except Exception as e:
        return image_bytes 

# --- 1. MEMUAT ENVIRONMENT VARIABLES & SUPABASE ---
load_dotenv()

url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")

try:
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Gagal terhubung ke Supabase: {e}")
    st.stop()

def upload_ke_supabase(file_bytes, file_path, content_type):
    bucket_name = "absensi-files"
    try:
        supabase.storage.from_(bucket_name).upload(
            path=file_path,
            file=file_bytes,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        return supabase.storage.from_(bucket_name).get_public_url(file_path)
    except Exception as e:
        st.error(f"Gagal upload ke server Storage: {e}")
        return None

@st.dialog("Peringatan File CSV ⚠️")
def tampilkan_peringatan_csv():
    st.write("Gagal memproses file: Terdapat **sel atau baris kosong** di dalam file CSV Anda.")
    st.write("Pastikan semua data terisi penuh dan hapus baris kosong di bagian paling bawah tabel, lalu coba upload ulang.")
    if st.button("Oke, Saya Mengerti", key="btn_close_dialog_csv", use_container_width=True):
        st.rerun()

# --- 1.5. FUNGSI KRIPTOGRAFI KEAMANAN ---
SECRET_KEY = os.environ.get("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET")
SUPERADMIN_PASSWORD = os.environ.get("SUPERADMIN_PASSWORD") or st.secrets.get("SUPERADMIN_PASSWORD")

if not SECRET_KEY or not SUPERADMIN_PASSWORD:
    st.error("🔒 KUNCI RAHASIA TIDAK DITEMUKAN! Pastikan COOKIE_SECRET dan SUPERADMIN_PASSWORD terisi.")
    st.stop()

def generate_signed_token(role_name: str) -> str:
    signature = hmac.new(SECRET_KEY.encode(), role_name.encode(), hashlib.sha256).hexdigest()
    return f"{role_name}|{signature}"

def verify_and_get_role(token: str):
    if not token or "|" not in token:
        return None
    parts = token.split("|", 1)
    role_name, client_signature = parts[0], parts[1]
    expected_signature = hmac.new(SECRET_KEY.encode(), role_name.encode(), hashlib.sha256).hexdigest()
    if hmac.compare_digest(client_signature, expected_signature):
        return role_name
    return None
    
# --- 2. KONFIGURASI HALAMAN & COOKIE ---
st.set_page_config(page_title="Sistem Absensi Sekolah Cabdis Wil IV", page_icon="🏫", layout="centered")
cookie_manager = stx.CookieManager(key="cookie_manager_utama")

# --- 3. CUSTOM CSS ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Poppins', sans-serif !important; }
    header {visibility: hidden !important; height: 0px !important;} 
    [data-testid="stToolbar"], [data-testid="stDecoration"], footer, #MainMenu {visibility: hidden !important;}
    [data-testid="stHeaderActionElements"], .header-anchor { display: none !important; }
    .block-container { padding-top: 2rem !important; }
    .stForm, div[data-testid="stExpander"] {
        background-color: #FFFFFF; padding: 24px; border-radius: 12px;
        box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.05); border: 1px solid #E2E8F0;
    }
    div.stButton > button {
        background-color: #2563EB !important; color: white !important; font-weight: 600 !important;
        border-radius: 8px !important; border: none !important; transition: 0.3s;
    }
    div.stButton > button:hover { background-color: #1D4ED8 !important; box-shadow: 0 4px 10px rgba(37, 99, 235, 0.3); }
    [data-testid="stSidebar"] { background-color: #F8FAFC !important; border-right: 1px solid #E2E8F0; }
    </style>
""", unsafe_allow_html=True)

# --- 4. FUNGSI INTERAKSI DATABASE (OPTIMASI EGRESS) ---
def get_data_sekolah():
    try:
        res = supabase.table('sekolah').select('school_name, lat, lng, radius_m').execute()
        if res.data: return pd.DataFrame(res.data)
    except: pass
    return pd.DataFrame(columns=['school_name', 'lat', 'lng', 'radius_m'])

def get_data_pegawai():
    try:
        # OPTIMASI: Tidak memanggil kolom photo_base64 secara massal!
        res = supabase.table('pegawai').select('nip, name, school_name, photo_uploaded, is_cadar').execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['nip'] = df['nip'].astype(str)
            return df
    except: pass
    return pd.DataFrame(columns=['nip', 'name', 'school_name', 'photo_uploaded', 'is_cadar'])

def get_data_admin():
    try:
        res = supabase.table('admins').select('id, username, password, sekolah').execute()
        if res.data: return pd.DataFrame(res.data)
    except: pass
    return pd.DataFrame(columns=['id', 'username', 'password', 'sekolah'])

def get_data_pengaturan():
    try:
        res = supabase.table('pengaturan').select('batas_masuk, batas_pulang').execute()
        if res.data:
            return pd.DataFrame(res.data)
        else:
            default_data = {'batas_masuk': '07:30', 'batas_pulang': '16:00'}
            supabase.table('pengaturan').insert(default_data).execute()
            return pd.DataFrame([default_data])
    except:
        return pd.DataFrame([{'batas_masuk': '07:30', 'batas_pulang': '16:00'}])

# --- 5. INISIALISASI SESSION STATE ---
for key_state, val in {'role': None, 'admin_sekolah': "Semua Sekolah", 'logout_triggered': False, 'wajah_terverifikasi': False}.items():
    if key_state not in st.session_state: st.session_state[key_state] = val

if 'schools' not in st.session_state: st.session_state.schools = get_data_sekolah()
if 'employees' not in st.session_state: st.session_state.employees = get_data_pegawai()
if 'settings' not in st.session_state: st.session_state.settings = get_data_pengaturan()

raw_token = cookie_manager.get("auth_token")
saved_admin_school = cookie_manager.get("admin_sekolah")
if saved_admin_school: st.session_state.admin_sekolah = saved_admin_school

valid_role = verify_and_get_role(raw_token)

if st.session_state.role is not None:
    st.session_state.logout_triggered = False
elif st.session_state.logout_triggered:
    if raw_token is None: st.session_state.logout_triggered = False 
else:
    if valid_role: st.session_state.role = valid_role
    elif raw_token and not valid_role:
        st.session_state.role = None
        try:
            cookie_manager.delete("auth_token", key="del_auth_invalid_role")
            cookie_manager.delete("admin_sekolah", key="del_sch_invalid_role")
        except: pass

def logout():
    st.session_state.role = None
    st.session_state.admin_sekolah = "Semua Sekolah"
    st.session_state.logout_triggered = True 
    st.session_state.wajah_terverifikasi = False 
    try:
        cookie_manager.delete("auth_token", key="delete_auth_token_btn")
        cookie_manager.delete("role", key="delete_role_btn") 
        cookie_manager.delete("admin_sekolah", key="delete_admin_sekolah_btn") 
    except: pass

# ==========================================
# HALAMAN LOGIN UTAMA
# ==========================================
if st.session_state.role is None:
    st.title("📍 Portal Presensi Sekolah CABDIS WIL IV")
    st.info("Selamat datang! Untuk merekam kehadiran Anda, silakan klik tombol di bawah ini.")

    if st.button("📸 Mulai Presensi Wajah & GPS", type="primary", use_container_width=True, key="btn_login_pegawai_main"):
        st.session_state.role = "Pegawai"
        st.session_state.wajah_terverifikasi = False
        cookie_manager.set("auth_token", generate_signed_token("Pegawai"), key="set_token_login_pegawai")
        time.sleep(0.5)
        st.rerun()

    st.write("---")
    st.caption("Akses khusus Pengelola Sistem:")
    col_admin, col_super = st.columns(2)

    with col_admin:
        with st.expander("🔑 Login Admin"):
            input_user_admin = st.text_input("Username Admin:", key="user_admin_main")
            pwd = st.text_input("Password Admin:", type="password", key="pwd_admin_main")
            if st.button("Masuk Admin", use_container_width=True, key="btn_admin_main"):
                df_adm = get_data_admin()
                is_valid = False
                assigned_school = "Semua Sekolah"
                if not df_adm.empty and 'username' in df_adm.columns:
                    match = df_adm[(df_adm['username'] == input_user_admin) & (df_adm['password'] == pwd)]
                    if not match.empty:
                        is_valid = True
                        assigned_school = match.iloc[0]['sekolah']
                if is_valid: 
                    st.session_state.role = "Admin"
                    st.session_state.admin_sekolah = assigned_school
                    cookie_manager.set("auth_token", generate_signed_token("Admin"), key="set_token_login_admin")
                    cookie_manager.set("admin_sekolah", assigned_school, key="set_sch_login_admin")
                    time.sleep(0.5)
                    st.rerun()
                else: st.error("Username atau Password Salah!")

    with col_super:
        with st.expander("🛠️ Login Superadmin"):
            pwd_super = st.text_input("Password Superadmin:", type="password", key="pwd_super_main")
            if st.button("Masuk Superadmin", use_container_width=True, key="btn_super_main"):
                if pwd_super == SUPERADMIN_PASSWORD:
                    st.session_state.role = "Superadmin"
                    cookie_manager.set("auth_token", generate_signed_token("Superadmin"), key="set_token_login_super")
                    time.sleep(0.5)
                    st.rerun()
                else: st.error("Password Salah!")
    st.stop()

# ==========================================
# SIDEBAR
# ==========================================
st.sidebar.title("Informasi Akun")
st.sidebar.success(f"Akses: **{st.session_state.role}**")
if st.session_state.role == "Admin": st.sidebar.caption(f"Unit Kerja: {st.session_state.admin_sekolah}")
st.sidebar.button("🚪 Keluar (Logout)", on_click=logout, key="btn_logout_sidebar")
st.sidebar.write("---")
waktu_sekarang = datetime.datetime.now(pytz.timezone('Asia/Makassar'))
st.sidebar.markdown("**Waktu Server (WITA):**")
st.sidebar.info(f"🕒 {waktu_sekarang.strftime('%H:%M:%S')} WITA\n\n📅 {waktu_sekarang.strftime('%d-%m-%Y')}")
st.sidebar.caption("Jam ini yang akan terekam di absensi.")
st.sidebar.write("---")

# ==========================================
# HAK AKSES 1: PEGAWAI
# ==========================================
if st.session_state.role == "Pegawai":
    st.button("⬅️ Kembali ke Halaman Awal", on_click=logout, key="btn_back_pegawai")
    st.title("📍 Presensi GPS & Wajah")
    nip_input = st.text_input("SILAHKAN KETIK NIP:", placeholder="Contoh: 198001012005011001", key="nip_input_pegawai")
    
    if nip_input.strip():
        try:
            # OPTIMASI: Panggil data foto HANYA saat NIP ini login
            res_pegawai = supabase.table('pegawai').select('nip, name, school_name, photo_uploaded, photo_base64, is_cadar').eq('nip', str(nip_input.strip())).execute()
            df_kandidat = pd.DataFrame(res_pegawai.data) if res_pegawai.data else pd.DataFrame()
        except: df_kandidat = pd.DataFrame()
            
        if df_kandidat.empty:
            st.warning("⚠️ Data pegawai tidak ditemukan.")
        else:
            emp_data = df_kandidat.iloc[0]
            try: sch_data = st.session_state.schools[st.session_state.schools['school_name'] == emp_data['school_name']].iloc[0]
            except:
                st.error("Data sekolah untuk pegawai ini tidak ditemukan.")
                st.stop()
                
            curr_dev_cookie = cookie_manager.get("school_device_token")
            try:
                res_dev_count = supabase.table('perangkat_sekolah').select('id').eq('school_name', sch_data['school_name']).execute()
                total_terdaftar = len(res_dev_count.data) if res_dev_count.data else 0
            except: total_terdaftar = 0

            is_valid_pc = False
            if total_terdaftar > 0:
                try:
                    res_valid = supabase.table('perangkat_sekolah').select('id').eq('school_name', sch_data['school_name']).eq('device_id', str(curr_dev_cookie)).execute()
                    if res_valid.data: is_valid_pc = True
                except: pass
                
                if not is_valid_pc:
                    st.error("⛔ AKSES DITOLAK! Perangkat ini belum terdaftar sebagai PC Resmi Sekolah.")
                    st.stop()
                else: st.success("🖥️ Perangkat Terverifikasi: PC Resmi Sekolah.")
            else:
                st.warning("⚠️ Sekolah ini belum mendaftarkan PC Resmi. Presensi di perangkat apapun masih terbuka.")
                
            st.info(f"👤 Nama: **{emp_data['name']}**\n\n🏫 Anda ditugaskan di: **{sch_data['school_name']}**")
            loc = get_geolocation()
            
            if loc:
                user_lat, user_lng = loc['coords']['latitude'], loc['coords']['longitude']
                jarak_meter = geopy.distance.geodesic((user_lat, user_lng), (sch_data['lat'], sch_data['lng'])).meters
                
                if jarak_meter <= sch_data['radius_m']:
                    st.success(f"✅ Lokasi Valid! Jarak: {jarak_meter:.0f} meter dari pusat.")
                    
                    is_uploaded = str(emp_data.get('photo_uploaded', 'False')).lower() == 'true'
                    is_cadar = str(emp_data.get('is_cadar', 'False')).lower() == 'true'
                    
                    if not is_cadar and not (is_uploaded and pd.notna(emp_data.get('photo_base64'))):
                        st.warning("⚠️ Admin belum mengunggah foto acuan wajah Anda.")
                    else:
                        img_camera = st.camera_input("Ambil Foto di Lokasi", key="cam_pegawai_input")
                        
                        if is_cadar:
                            st.session_state.wajah_terverifikasi = True
                            st.info("🧕 Verifikasi biometrik dilewati (Mode Audit).")

                        if img_camera:
                            bytes_data = kompres_foto(img_camera.getvalue())
                            cam_base64 = f"data:image/jpeg;base64,{base64.b64encode(bytes_data).decode('utf-8')}"
                            tgl_sekarang_str = datetime.datetime.now(pytz.timezone('Asia/Makassar')).strftime('%Y%m%d_%H%M%S')
                            url_foto_harian = upload_ke_supabase(bytes_data, f"foto_presensi/{emp_data['nip']}_{tgl_sekarang_str}.jpg", "image/jpeg")
                            
                            if not is_cadar:
                                html_code = f"""
                                <!DOCTYPE html>
                                <html>
                                <head><script src="https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/dist/face-api.js"></script></head>
                                <body style="text-align: center; font-family: sans-serif; margin:0; padding:5px;">
                                    <div id="status" style="color:#d9534f; font-weight:bold;">Memuat AI...</div>
                                    <div id="kode" style="display:none; color:white; background:#5cb85c; padding:8px; border-radius:5px; font-weight:bold;">✅ WAJAH COCOK</div>
                                    <img id="refImg" crossorigin="anonymous" src="{emp_data.get('photo_base64', '')}" style="display:none;" />
                                    <img id="camImg" src="{cam_base64}" style="display:none;" />
                                    <script>
                                        async function runAI() {{
                                            const status = document.getElementById('status');
                                            try {{
                                                const URL = 'https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/model';
                                                await faceapi.nets.ssdMobilenetv1.loadFromUri(URL);
                                                await faceapi.nets.faceLandmark68Net.loadFromUri(URL);
                                                await faceapi.nets.faceRecognitionNet.loadFromUri(URL);
                                                const ref = await faceapi.detectSingleFace(document.getElementById('refImg')).withFaceLandmarks().withFaceDescriptor();
                                                const cam = await faceapi.detectSingleFace(document.getElementById('camImg')).withFaceLandmarks().withFaceDescriptor();
                                                if(!ref || !cam) {{ status.innerText = "⚠️ Wajah tidak jelas."; return; }}
                                                const match = new faceapi.FaceMatcher(ref).findBestMatch(cam.descriptor);
                                                if(match.distance <= 0.5) {{ 
                                                    status.style.display = "none";
                                                    document.getElementById('kode').style.display = "inline-block";
                                                    try {{
                                                        window.parent.document.querySelectorAll('p').forEach(p => {{
                                                            if(p.innerText === "V_E_R_I_F_I_E_D") p.closest('button').click();
                                                        }});
                                                    }} catch(err) {{}}
                                                }} else {{ status.innerText = "⛔ WAJAH TIDAK COCOK!"; }}
                                            }} catch(e) {{ status.innerText = "Gagal memuat AI."; }}
                                        }}
                                        setTimeout(runAI, 500);
                                    </script>
                                </body>
                                </html>
                                """
                                components.html(html_code, height=60, scrolling=False)

                                if not st.session_state.wajah_terverifikasi:
                                    st.markdown('<style>div.stButton > button:has(p:contains("V_E_R_I_F_I_E_D")) {opacity: 0; height: 1px; pointer-events: none;}</style>', unsafe_allow_html=True)
                                    if st.button("V_E_R_I_F_I_E_D", key="btn_hidden_trigger"):
                                        st.session_state.wajah_terverifikasi = True
                                        st.rerun()
                                    
                            if st.session_state.wajah_terverifikasi:
                                col_masuk, col_pulang = st.columns(2)
                                btn_masuk = col_masuk.button("📥 MASUK", type="primary", use_container_width=True, key="btn_absen_masuk")
                                btn_pulang = col_pulang.button("📤 PULANG", use_container_width=True, key="btn_absen_pulang")
                                    
                                if btn_masuk or btn_pulang:
                                    now = datetime.datetime.now(pytz.timezone('Asia/Makassar'))
                                    tgl_sekarang = now.strftime('%Y-%m-%d')
                                    jenis_aksi = "Masuk" if btn_masuk else "Pulang"
                                    
                                    try:
                                        res_absen = supabase.table('absensi').select('status').eq('nip', str(emp_data['nip'])).eq('tanggal', tgl_sekarang).execute()
                                        df_absen_hari_ini = pd.DataFrame(res_absen.data) if res_absen.data else pd.DataFrame()
                                    except: df_absen_hari_ini = pd.DataFrame()
                                    
                                    if not df_absen_hari_ini.empty and not df_absen_hari_ini[df_absen_hari_ini['status'].str.contains(jenis_aksi, na=False, case=False)].empty:
                                        st.warning(f"⚠️ Anda sudah absen **{jenis_aksi}** hari ini!")
                                    else:
                                        jam_sekarang = now.time()
                                        try:
                                            b_masuk_str = st.session_state.settings['batas_masuk'].iloc[0] if not st.session_state.settings.empty else '07:30'
                                            b_pulang_str = st.session_state.settings['batas_pulang'].iloc[0] if not st.session_state.settings.empty else '16:00'
                                            batas_masuk_obj = datetime.datetime.strptime(b_masuk_str, '%H:%M').time()
                                            batas_pulang_obj = datetime.datetime.strptime(b_pulang_str, '%H:%M').time()
                                        except:
                                            batas_masuk_obj, batas_pulang_obj = datetime.time(7, 30), datetime.time(16, 0)
                                        
                                        if btn_masuk:
                                            jenis_absen = "Masuk (TERLAMBAT)" if jam_sekarang > batas_masuk_obj else "Masuk (Tepat Waktu)"
                                        else:
                                            jenis_absen = "Pulang (LEBIH AWAL)" if jam_sekarang < batas_pulang_obj else "Pulang (Tepat Waktu)"

                                        status_final = f"Hadir {'[Audit] ' if is_cadar else ''}- {jenis_absen}"
                                        
                                        supabase.table('absensi').insert({
                                            'nip': str(emp_data['nip']), 'nama': emp_data['name'], 
                                            'sekolah': sch_data['school_name'], 'tanggal': tgl_sekarang, 
                                            'jam': now.strftime('%H:%M:%S'), 'jarak_m': str(round(jarak_meter, 1)), 
                                            'status': status_final, 'foto_bukti': url_foto_harian if url_foto_harian else "" 
                                        }).execute()
                                        st.success(f"✅ Absensi {jenis_absen} berhasil!")
                            else: st.warning("Tunggu verifikasi biometrik selesai...")
                else: st.error(f"⛔ Anda berada di luar radius ({jarak_meter:.0f} m dari {sch_data['radius_m']} m).")
            else: st.warning("Menunggu akses GPS...")

# ==========================================
# HAK AKSES 2: ADMIN
# ==========================================
elif st.session_state.role == "Admin":
    col_judul, col_tombol = st.columns([3, 1])
    col_judul.title("🔐 Dashboard Admin")
    col_tombol.button("🚪 Logout", on_click=logout, use_container_width=True, key="btn_logout_top_admin")
    admin_akses = st.session_state.get('admin_sekolah', 'Semua Sekolah')

    # --- 1. KELOLA PC ABSENSI ---
    st.markdown("### 🖥️ 1. Kelola PC Absensi Sekolah")
    with st.expander("📌 Pendaftaran & Daftar PC", expanded=True):
        try:
            res_pc = supabase.table('perangkat_sekolah').select('id, device_name').eq('school_name', admin_akses).execute()
            list_pc = res_pc.data if res_pc.data else []
        except: list_pc = []

        total_terdaftar = len(list_pc)
        st.markdown("##### ➕ Daftarkan PC Ini")
        st.caption(f"Status Kuota Perangkat: **{total_terdaftar} dari 2 PC Terdaftar**")

        if total_terdaftar >= 2:
            st.warning("🔒 **PENDAFTARAN TERKUNCI!** Hubungi Superadmin.")
        else:
            nama_pc_input = st.text_input("Nama/Label PC", key="inp_nama_pc_baru")
            if st.button("📌🛠️ Daftarkan PC Ini", key="btn_register_pc_dynamic"):
                if admin_akses == "Semua Sekolah": st.error("Login spesifik sebagai admin sekolah diperlukan.")
                elif nama_pc_input.strip():
                    new_token = str(uuid.uuid4())
                    cookie_manager.set("school_device_token", new_token, key="set_pc_cookie_dyn")
                    supabase.table('perangkat_sekolah').insert({'school_name': admin_akses, 'device_id': new_token, 'device_name': nama_pc_input.strip()}).execute()
                    st.success("✅ PC berhasil didaftarkan!")
                    time.sleep(1)
                    st.rerun()
                else: st.error("Masukkan label PC.")

        st.markdown("##### 📋 Daftar PC Terdaftar")
        if list_pc:
            for r_pc in list_pc: st.write(f"🖥️ **{r_pc['device_name']}** - 🔒 Terkunci")
        else: st.info("Belum ada PC terdaftar.")
    
    # --- 2. KELOLA FOTO ACUAN ---
    st.markdown("### 📸 2. Kelola Foto Acuan")
    col_f1, col_f2 = st.columns(2)
    opsi_sekolah_foto = ["Semua Sekolah"] + st.session_state.schools['school_name'].tolist()
    sekolah_pilihan_foto = col_f1.selectbox("🏢 Filter Sekolah:", opsi_sekolah_foto if admin_akses == "Semua Sekolah" else [admin_akses], disabled=(admin_akses != "Semua Sekolah"))
    search_query_foto = col_f2.text_input("🔍 Cari NIP atau Nama:", key="search_admin_foto")
    
    if search_query_foto.strip():
        try:
            # OPTIMASI: Panggil photo_base64 hanya saat spesifik mencari!
            query = supabase.table('pegawai').select('nip, name, school_name, photo_uploaded, photo_base64, is_cadar')
            if sekolah_pilihan_foto != "Semua Sekolah": query = query.eq('school_name', sekolah_pilihan_foto)
            res_search = query.or_(f"nip.ilike.%{search_query_foto}%,name.ilike.%{search_query_foto}%").execute()
            df_kandidat = pd.DataFrame(res_search.data) if res_search.data else pd.DataFrame()
        except: df_kandidat = pd.DataFrame()
            
        if not df_kandidat.empty:
            for index, emp in df_kandidat.iterrows():
                nip, nama, is_cadar, is_uploaded = str(emp['nip']), emp['name'], str(emp.get('is_cadar', 'False')).lower() == 'true', str(emp.get('photo_uploaded', False)).lower() == 'true'
                status_simbol = "🧕" if is_cadar else ("🟢" if is_uploaded else "🔴")
                with st.expander(f"{status_simbol} {nama} — NIP: {nip}"):
                    col_kiri, col_kanan = st.columns([1, 2])
                    if is_uploaded and pd.notna(emp.get('photo_base64')) and emp['photo_base64']: col_kiri.image(emp['photo_base64'], use_container_width=True)
                    else: col_kiri.info("📷 Belum ada foto")
                            
                    col_kanan.markdown(f"**Unit:** {emp['school_name']}")
                    if is_uploaded: col_kanan.error("🔒 Foto terkunci.")
                    else:
                        foto = col_kanan.file_uploader("Upload Foto", type=['jpg', 'jpeg', 'png'], key=f"foto_up_{nip}")
                        if foto and col_kanan.button("💾 Simpan", key=f"btn_save_foto_{nip}", use_container_width=True):
                            file_bytes = kompres_foto(foto.getvalue(), quality=60, max_size=(600, 600))
                            url_foto = upload_ke_supabase(file_bytes, f"foto_acuan/{nip}.jpg", "image/jpeg")
                            if url_foto:
                                supabase.table('pegawai').update({'photo_uploaded': True, 'photo_base64': url_foto}).eq('nip', nip).execute()
                                st.session_state.employees = get_data_pegawai()
                                st.rerun()

    # --- 3. REKAP HARIAN ---
    st.markdown("### 📋 3. Rekap Harian")
    with st.form("form_filter_rekap"):
        tgl_pilihan = st.date_input("Tanggal:")
        opsi_sekolah = ["-- Pilih Sekolah --", "Semua Sekolah"] + st.session_state.schools['school_name'].tolist()
        sekolah_pilihan = st.selectbox("Sekolah:", opsi_sekolah if admin_akses == "Semua Sekolah" else [admin_akses], disabled=(admin_akses != "Semua Sekolah"))
        if st.form_submit_button("📊 TAMPILKAN"): st.session_state.show_data_rekap = (sekolah_pilihan != "-- Pilih Sekolah --")

    if st.session_state.get('show_data_rekap', False):
        df_emp = st.session_state.employees.copy()
        if sekolah_pilihan != "Semua Sekolah": df_emp = df_emp[df_emp['school_name'] == sekolah_pilihan]
        
        if not df_emp.empty:
            tgl_str = tgl_pilihan.strftime('%Y-%m-%d')
            try:
                # OPTIMASI: Abaikan foto_bukti (mengurangi egress drastis)
                res_absen_admin = supabase.table('absensi').select('nip, status, jam, jarak_m').eq('tanggal', tgl_str).execute()
                df_absen_tgl = pd.DataFrame(res_absen_admin.data) if res_absen_admin.data else pd.DataFrame()
            except: df_absen_tgl = pd.DataFrame()
            
            rekap_list = []
            for _, emp in df_emp.iterrows():
                nip = str(emp['nip'])
                data_absen = df_absen_tgl[df_absen_tgl['nip'] == nip] if not df_absen_tgl.empty else pd.DataFrame()
                jam_masuk = jam_pulang = jarak = '-'
                status_final = 'Tanpa Keterangan'
                
                if not data_absen.empty:
                    am = data_absen[data_absen['status'].str.contains('Masuk', na=False, case=False)]
                    ap = data_absen[data_absen['status'].str.contains('Pulang', na=False, case=False)]
                    al = data_absen[~data_absen['status'].str.contains('Hadir|Masuk|Pulang', na=False, case=False)]
                    
                    if not am.empty: jam_masuk, jarak, status_final = am.iloc[0]['jam'], am.iloc[0]['jarak_m'], am.iloc[0]['status']
                    if not ap.empty: 
                        jam_pulang = ap.iloc[0]['jam']
                        if jarak == '-': jarak = ap.iloc[0]['jarak_m']
                        status_final = f"{status_final} & {ap.iloc[0]['status']}" if not am.empty else ap.iloc[0]['status']
                    if not al.empty: status_final, jarak = al.iloc[0]['status'], al.iloc[0]['jarak_m']
                        
                rekap_list.append({'NIP': nip, 'NAMA': emp['name'], 'SEKOLAH': emp['school_name'], 'TANGGAL': tgl_str, 'JARAK': str(jarak), 'MASUK': jam_masuk, 'PULANG': jam_pulang, 'STATUS': status_final})
                
            df_rekap = pd.DataFrame(rekap_list)
            st.dataframe(df_rekap, use_container_width=True)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_rekap.to_excel(writer, index=False)
            st.download_button("📥 Download Excel", buffer.getvalue(), f"Rekap_{tgl_str}.xlsx")
            
    # --- 4. REKAP BULANAN ---
    st.markdown("### 📊 4. Rekap Bulanan")
    col_rek1, col_rek2 = st.columns(2)
    filter_sch_rekap = col_rek1.selectbox("Pilih Sekolah:", ["-- Pilih Sekolah --"] + st.session_state.schools['school_name'].tolist() if admin_akses == "Semua Sekolah" else [admin_akses], disabled=(admin_akses != "Semua Sekolah"))
    month_options = [(datetime.datetime.now() - datetime.timedelta(days=30*i)).strftime('%Y-%m') for i in range(12)]
    filter_bln_rekap = col_rek2.selectbox("Bulan:", month_options)
        
    if st.button("📈 Tampilkan Rekap Bulanan", type="primary"):
        if filter_sch_rekap != "-- Pilih Sekolah --":
            with st.spinner("Menghitung kalkulasi..."):
                try:
                    res_peg = supabase.table('pegawai').select('nip, name').eq('school_name', filter_sch_rekap).execute()
                    
                    # OPTIMASI EGRESS: Hanya memanggil nip, tanggal, jam, status. (Ribuan row jauh lebih ringan)
                    res_abs = supabase.table('absensi').select('nip, tanggal, jam, status').eq('sekolah', filter_sch_rekap).like('tanggal', f"{filter_bln_rekap}%").limit(5000).execute()
                    
                    if res_peg.data:
                        rekap_data = {str(p['nip']): {'NIP': str(p['nip']), 'NAMA': p['name'], 'MENIT TERLAMBAT': 0, 'MENIT CEPAT PULANG': 0, 'JUMLAH KEHADIRAN': 0, 'TANPA KETERANGAN': 0, 'SAKIT': 0, 'DINAS LUAR': 0, 'CUTI': 0, '_tdk': 0} for p in res_peg.data}
                        abs_dict = {}
                        if res_abs.data:
                            for a in res_abs.data:
                                nip, tgl = str(a['nip']), a['tanggal']
                                abs_dict.setdefault(nip, {}).setdefault(tgl, []).append(a)
                            
                        # Format standard output dataframe
                        df_rekap = pd.DataFrame(list(rekap_data.values())).drop(columns=['_tdk'])
                        st.dataframe(df_rekap, use_container_width=True)
                        buffer = io.BytesIO()
                        with pd.ExcelWriter(buffer, engine='openpyxl') as writer: df_rekap.to_excel(writer, index=False)
                        st.download_button("📥 Download Excel", buffer.getvalue(), f"Rekap_{filter_bln_rekap}.xlsx")
                except Exception as e: st.error(f"Gagal memuat rekap: {e}")

# ==========================================
# HAK AKSES 3: SUPERADMIN
# ==========================================
elif st.session_state.role == "Superadmin":
    col_judul, col_tombol = st.columns([3, 1])
    col_judul.title("🛠️ Dashboard Superadmin")
    col_tombol.button("🚪 Logout", on_click=logout, use_container_width=True)
    
    tab1, tab_pc, tab2, tab3, tab4, tab5, tab6 = st.tabs(["🏛️ Sekolah", "💻 PC", "👥 Pegawai", "🔑 Admin", "📝 Izin", "🚨 Database", "⚙️ Jam"])
    
    with tab1:
        st.markdown("### Sekolah Aktif")
        edited_schools = st.data_editor(st.session_state.schools, num_rows="dynamic", use_container_width=True)
        if st.button("💾 Simpan Perubahan Sekolah", type="primary"):
            records = edited_schools.to_dict(orient='records')
            if records: supabase.table('sekolah').upsert(records, on_conflict='school_name').execute()
            st.session_state.schools = get_data_sekolah()
            st.rerun()

    with tab_pc:
        st.markdown("### Buka Kunci PC")
        sekolah_pilihan_pc = st.selectbox("Filter Sekolah:", ["Semua Sekolah"] + st.session_state.schools['school_name'].tolist())
        try:
            query_pc = supabase.table('perangkat_sekolah').select('id, school_name, device_name')
            if sekolah_pilihan_pc != "Semua Sekolah": query_pc = query_pc.eq('school_name', sekolah_pilihan_pc)
            res_pc_super = query_pc.execute()
            if res_pc_super.data:
                for idx, r_pc in pd.DataFrame(res_pc_super.data).iterrows():
                    c1, c2, c3 = st.columns([2, 2, 1])
                    c1.write(r_pc['school_name']); c2.write(r_pc['device_name'])
                    if c3.button("🔓 Hapus Kunci", key=f"del_{r_pc['id']}"):
                        supabase.table('perangkat_sekolah').delete().eq('id', r_pc['id']).execute()
                        st.rerun()
        except: pass

    with tab2:
        st.markdown("### Upload Pegawai Massal (CSV/Excel)")
        file_upload = st.file_uploader("Upload Excel", type=['xlsx', 'xls'])
        if file_upload and st.button("Proses Upload"):
            try:
                df_upload = pd.read_excel(file_upload, dtype=str).dropna(subset=['nip', 'name', 'school_name'], how='all')
                records = [{'nip': str(r['nip']).strip(), 'name': str(r['name']).strip(), 'school_name': str(r['school_name']).strip(), 'photo_uploaded': False, 'is_cadar': False} for _, r in df_upload.iterrows()]
                supabase.table('pegawai').upsert(records, on_conflict='nip').execute()
                st.session_state.employees = get_data_pegawai()
                st.success("✅ Berhasil upload pegawai!")
                st.rerun()
            except Exception as e: st.error(f"Gagal: {e}")

    with tab3:
        st.markdown("### Kelola Admin")
        df_admins = get_data_admin()
        for idx, row in df_admins.iterrows():
            with st.expander(f"👤 {row['username']} - {row['sekolah']}"):
                if st.button("🗑️ Hapus Admin", key=f"del_adm_{idx}"):
                    supabase.table('admins').delete().eq('id', row['id']).execute()
                    st.rerun()

    with tab4:
        st.markdown("### Input Izin / Surat (Bypass)")
        nip_input_izin = st.text_input("NIP Pegawai:")
        if st.button("Input Surat Kosong/Izin") and nip_input_izin:
            supabase.table('absensi').insert({'nip': nip_input_izin, 'nama': 'Manual', 'sekolah': 'Manual', 'tanggal': datetime.datetime.now().strftime('%Y-%m-%d'), 'jam': '-', 'status': 'Izin'}).execute()
            st.success("Izin dicatat!")

    with tab5:
        st.markdown("### 🚨 Database Clean Up")
        if st.button("🖼️ Hapus Semua Foto (Teks Aman)", type="primary"):
            supabase.table('absensi').update({'foto_bukti': ''}).neq('foto_bukti', '').execute()
            st.success("Foto fisik berhasil diputus dari database (Hemat Egress).")

    with tab6:
        st.markdown("### ⚙️ Jam Kerja")
        b_in = st.session_state.settings['batas_masuk'].iloc[0] if not st.session_state.settings.empty else '07:30'
        b_out = st.session_state.settings['batas_pulang'].iloc[0] if not st.session_state.settings.empty else '16:00'
        n_in = st.time_input("Batas Masuk", datetime.datetime.strptime(b_in, '%H:%M').time())
        n_out = st.time_input("Batas Pulang", datetime.datetime.strptime(b_out, '%H:%M').time())
        if st.button("Simpan Pengaturan"):
            supabase.table('pengaturan').update({'batas_masuk': n_in.strftime('%H:%M'), 'batas_pulang': n_out.strftime('%H:%M')}).neq('batas_masuk', '').execute()
            st.session_state.settings = get_data_pengaturan()
            st.rerun()
