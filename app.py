import io
import hmac
import hashlib
import streamlit as st
import pandas as pd
import datetime
import pytz
import base64
import os
import time
import geopy.distance
from streamlit_js_eval import get_geolocation
import streamlit.components.v1 as components
import extra_streamlit_components as stx
from dotenv import load_dotenv
from supabase import create_client, Client

# --- 1. MEMUAT ENVIRONMENT VARIABLES & SUPABASE ---
load_dotenv()

url = os.environ.get("SUPABASE_URL") or st.secrets.get("SUPABASE_URL", "")
key = os.environ.get("SUPABASE_KEY") or st.secrets.get("SUPABASE_KEY", "")

try:
    supabase: Client = create_client(url, key)
except Exception as e:
    st.error(f"Gagal terhubung ke Supabase: {e}")
    st.stop()

# --- 1.5. FUNGSI KRIPTOGRAFI KEAMANAN COOKIE (HMAC) ---
# Secret Key diambil dari .env / st.secrets, pastikan ganti dengan string acak yang panjang
SECRET_KEY = os.environ.get("COOKIE_SECRET") or st.secrets.get("COOKIE_SECRET", "kunci_rahasia_absensi_sekolah_cabdis_wil_iv_987654321")

def generate_signed_token(role_name: str) -> str:
    """Membuat token dalam format 'ROLE|SIGNATURE'"""
    signature = hmac.new(SECRET_KEY.encode(), role_name.encode(), hashlib.sha256).hexdigest()
    return f"{role_name}|{signature}"

def verify_and_get_role(token: str):
    """Memvalidasi apakah token cookie asli dan belum diubah di F12 (Developer Tools)"""
    if not token or "|" not in token:
        return None
    
    parts = token.split("|", 1)
    role_name, client_signature = parts[0], parts[1]
    
    # Hitung signature resmi di server
    expected_signature = hmac.new(SECRET_KEY.encode(), role_name.encode(), hashlib.sha256).hexdigest()
    
    # Bandingkan signature dari client dengan signature asli server
    if hmac.compare_digest(client_signature, expected_signature):
        return role_name
    
    return None  # Jika signature tidak cocok (diubah di F12), kembalikan None!
    
# --- 2. KONFIGURASI HALAMAN & COOKIE ---
st.set_page_config(page_title="Sistem Absensi Sekolah Cabdis Wil IV", page_icon="🏫", layout="centered")

cookie_manager = stx.CookieManager(key="cookie_manager_utama")

# Folder lokal untuk penyimpanan surat izin
DIR_SURAT = "surat_izin"
if not os.path.exists(DIR_SURAT):
    os.makedirs(DIR_SURAT)

# --- 3. KUSTOMISASI TAMPILAN (CUSTOM CSS) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Poppins', sans-serif !important;
    }

    header {visibility: hidden !important; height: 0px !important;} 
    [data-testid="stToolbar"] {visibility: hidden !important;} 
    [data-testid="stDecoration"] {visibility: hidden !important;} 
    footer {visibility: hidden !important;} 
    #MainMenu {visibility: hidden !important;}
    
    /* Menyembunyikan ikon rantai / anchor link pada judul */
    [data-testid="stHeaderActionElements"], .header-anchor {
        display: none !important;
    }

    .block-container { padding-top: 2rem !important; }

    .stForm, div[data-testid="stExpander"] {
        background-color: #FFFFFF;
        padding: 24px;
        border-radius: 12px;
        box-shadow: 0px 4px 15px rgba(0, 0, 0, 0.05);
        border: 1px solid #E2E8F0;
    }

    div.stButton > button {
        background-color: #2563EB !important; 
        color: white !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        border: none !important;
        transition: 0.3s;
    }
    
    div.stButton > button:hover {
        background-color: #1D4ED8 !important; 
        box-shadow: 0 4px 10px rgba(37, 99, 235, 0.3);
    }
    
    [data-testid="stSidebar"] {
        background-color: #F8FAFC !important;
        border-right: 1px solid #E2E8F0;
    }
    </style>
""", unsafe_allow_html=True)

# --- 4. FUNGSI INTERAKSI DATABASE SUPABASE ---
def get_data_sekolah():
    try:
        res = supabase.table('sekolah').select('*').execute()
        if res.data:
            return pd.DataFrame(res.data)
    except Exception:
        pass
    return pd.DataFrame(columns=['school_name', 'lat', 'lng', 'radius_m'])

def get_data_pegawai():
    try:
        res = supabase.table('pegawai').select('*').execute()
        if res.data:
            df = pd.DataFrame(res.data)
            df['nip'] = df['nip'].astype(str)
            # Pastikan kolom is_cadar ada untuk mencegah error
            if 'is_cadar' not in df.columns:
                df['is_cadar'] = False
            return df
    except Exception:
        pass
    return pd.DataFrame(columns=['nip', 'name', 'school_name', 'photo_uploaded', 'photo_base64', 'is_cadar'])

def get_data_admin():
    try:
        res = supabase.table('admins').select('*').execute()
        if res.data:
            return pd.DataFrame(res.data)
    except Exception:
        pass
    return pd.DataFrame(columns=['id', 'username', 'password', 'sekolah'])

def get_data_pengaturan():
    try:
        res = supabase.table('pengaturan').select('*').execute()
        if res.data:
            return pd.DataFrame(res.data)
        else:
            default_data = {'batas_masuk': '07:30', 'batas_pulang': '16:00'}
            supabase.table('pengaturan').insert(default_data).execute()
            return pd.DataFrame([default_data])
    except Exception:
        return pd.DataFrame([{'batas_masuk': '07:30', 'batas_pulang': '16:00'}])

# --- 5. INISIALISASI SESSION STATE ---
if 'schools' not in st.session_state:
    st.session_state.schools = get_data_sekolah()

if 'employees' not in st.session_state:
    st.session_state.employees = get_data_pegawai()

if 'settings' not in st.session_state:
    st.session_state.settings = get_data_pengaturan()

# --- INISIALISASI SESSION STATE DASAR ---
if 'role' not in st.session_state:
    st.session_state.role = None
if 'logout_triggered' not in st.session_state:
    st.session_state.logout_triggered = False

# --- BACA STATUS COOKIE TERPROTEKSI HMAC ---
raw_token = cookie_manager.get(cookie="auth_token")
valid_role = verify_and_get_role(raw_token)

# --- LOGIKA SINKRONISASI ANTI-LAG ---
if st.session_state.role is not None:
    # 1. Jika user SUDAH login lewat tombol, pastikan flag logout mati
    st.session_state.logout_triggered = False
elif st.session_state.logout_triggered:
    # 2. Jika sedang proses logout, abaikan sisa cookie lama di browser sementara waktu
    if raw_token is None:
        st.session_state.logout_triggered = False # Reset flag jika cookie sudah benar-benar hilang
else:
    # 3. Mode Auto-Login (Kasus buka tab baru atau F5)
    if valid_role:
        st.session_state.role = valid_role
    elif raw_token and not valid_role:
        # Keamanan F12: Jika cookie ada tapi dimanipulasi, paksa logout
        st.session_state.role = None
        try:
            cookie_manager.delete("auth_token", key="force_del_auth")
        except KeyError:
            pass

# --- FUNGSI LOGOUT ---
def logout():
    st.session_state.role = None
    st.session_state.logout_triggered = True  # Mengaktifkan flag anti-bounce
    try:
        cookie_manager.delete("auth_token", key="delete_auth_token")
        cookie_manager.delete("role", key="delete_role") 
    except KeyError:
        pass

# ==========================================
# HALAMAN LOGIN UTAMA
# ==========================================
if st.session_state.role is None:
    st.title("📍 Portal Presensi Sekolah CABDIS WIL IV")
    st.info("Selamat datang! Untuk merekam kehadiran Anda, silakan klik tombol di bawah ini.")

    if st.button("📸 Mulai Presensi Wajah & GPS", type="primary", width="stretch"):
        st.session_state.role = "Pegawai"
        cookie_manager.set("auth_token", generate_signed_token("Pegawai"))
        time.sleep(0.5)
        st.rerun()

    st.write("---")

    st.caption("Akses khusus Pengelola Sistem:")
    col_admin, col_super = st.columns(2)

    with col_admin:
        with st.expander("🔑 Login Admin"):
            input_user_admin = st.text_input("Username Admin:", key="user_admin_main")
            pwd = st.text_input("Password Admin:", type="password", key="pwd_admin_main")
            if st.button("Masuk Admin", width="stretch", key="btn_admin_main"):
                df_adm = get_data_admin()
                is_valid = False

                if not df_adm.empty and 'username' in df_adm.columns:
                    match = df_adm[(df_adm['username'] == input_user_admin) & (df_adm['password'] == pwd)]
                    if not match.empty:
                        is_valid = True

                if is_valid: 
                    st.session_state.role = "Admin"
                    cookie_manager.set("auth_token", generate_signed_token("Admin"))
                    time.sleep(0.5)
                    st.rerun()
                else: 
                    st.error("Username atau Password Salah!")

    with col_super:
        with st.expander("🛠️ Login Superadmin"):
            pwd_super = st.text_input("Password Superadmin:", type="password", key="pwd_super_main")
            if st.button("Masuk Superadmin", width="stretch", key="btn_super_main"):
                # Mengambil password dari secrets atau .env, jika tidak ada fallback ke default
                superadmin_password = os.environ.get("SUPERADMIN_PASSWORD") or st.secrets.get("SUPERADMIN_PASSWORD", "superadmin123")
                
                if pwd_super == superadmin_password:
                    st.session_state.role = "Superadmin"
                    cookie_manager.set("auth_token", generate_signed_token("Superadmin"))
                    time.sleep(0.5)
                    st.rerun()
                else: 
                    st.error("Password Salah!")
    st.stop()

# ==========================================
# SIDEBAR
# ==========================================
st.sidebar.title("Informasi Akun")
st.sidebar.success(f"Akses: **{st.session_state.role}**")
st.sidebar.button("🚪 Keluar (Logout)", on_click=logout, key="btn_logout_utama")
st.sidebar.write("---")

waktu_sekarang = datetime.datetime.now(pytz.timezone('Asia/Makassar'))
st.sidebar.markdown("**Waktu Server (WITA):**")
st.sidebar.info(f"🕒 {waktu_sekarang.strftime('%H:%M:%S')} WITA\n\n📅 {waktu_sekarang.strftime('%d-%m-%Y')}")
st.sidebar.caption("Jam ini yang akan terekam di absensi, terlepas dari pengaturan jam di HP Anda.")
st.sidebar.write("---")

# ==========================================
# HAK AKSES 1: PEGAWAI
# ==========================================
if st.session_state.role == "Pegawai":
    st.button("⬅️ Kembali ke Halaman Awal", on_click=logout)
    st.title("📍 Presensi GPS & Wajah")
    
    st.session_state.employees = get_data_pegawai()
    st.session_state.schools = get_data_sekolah()
    
    if st.session_state.employees.empty:
        st.warning("Belum ada data pegawai. Hubungi Superadmin.")
    else:
        pegawai_pilihan = st.selectbox("Pilih Nama Anda:", st.session_state.employees['name'].tolist())
        emp_data = st.session_state.employees[st.session_state.employees['name'] == pegawai_pilihan].iloc[0]
        
        try:
            sch_data = st.session_state.schools[st.session_state.schools['school_name'] == emp_data['school_name']].iloc[0]
        except IndexError:
            st.error("Data sekolah untuk pegawai ini tidak ditemukan atau telah dihapus.")
            st.stop()
            
        st.info(f"🏫 Anda ditugaskan di: **{sch_data['school_name']}**")
        st.write("Lokasi sedang dideteksi secara otomatis. Mohon pastikan GPS aktif.")
        
        loc = get_geolocation()
        
        if loc:
            user_lat = loc['coords']['latitude']
            user_lng = loc['coords']['longitude']
            
            jarak_meter = geopy.distance.geodesic((user_lat, user_lng), (sch_data['lat'], sch_data['lng'])).meters
            
            if jarak_meter <= sch_data['radius_m']:
                st.success(f"✅ Lokasi Valid! Anda berada {jarak_meter:.0f} meter dari pusat sekolah.")
                st.markdown("### Rekam Kehadiran")
                
                # --- LOGIKA PENGECEKAN FOTO DAN CADAR ---
                is_uploaded = str(emp_data.get('photo_uploaded', 'False')).lower() == 'true'
                
                is_cadar = emp_data.get('is_cadar', False)
                if isinstance(is_cadar, str):
                    is_cadar = is_cadar.lower() == 'true'
                
                # Jika bukan akun cadar dan belum ada foto acuan, blokir akses
                if not is_cadar and not (is_uploaded and pd.notna(emp_data.get('photo_base64'))):
                    st.warning("⚠️ Admin belum mengunggah foto acuan wajah Anda. Harap hubungi Admin.")
                else:
                    # Ambil foto live (Berlaku untuk akun normal dan cadar)
                    img_camera = st.camera_input("Ambil Foto di Lokasi Sekolah")
                    
                    if img_camera:
                        bytes_data = img_camera.getvalue()
                        cam_base64 = f"data:image/jpeg;base64,{base64.b64encode(bytes_data).decode('utf-8')}"
                        
                        if not is_cadar:
                            # ==========================================
                            # LOGIKA 1: PEGAWAI NORMAL (VERIFIKASI AI)
                            # ==========================================
                            html_code = f"""
                            <!DOCTYPE html>
                            <html>
                            <head><script src="https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/dist/face-api.js"></script></head>
                            <body style="text-align: center; font-family: sans-serif; margin:0; padding:5px;">
                                <div id="status" style="color:#d9534f; font-weight:bold;">Memuat AI Verifikasi...</div>
                                <div id="kode" style="display:none; color:white; background:#5cb85c; padding:8px 15px; border-radius:5px; font-weight:bold; font-size:18px;">✅ WAJAH COCOK</div>
                                <img id="refImg" src="{emp_data.get('photo_base64', '')}" style="display:none;" />
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
                                            
                                            if(!ref || !cam) {{ status.innerText = "⚠️ Wajah tidak terdeteksi jelas pada kamera."; return; }}
                                            
                                            const match = new faceapi.FaceMatcher(ref).findBestMatch(cam.descriptor);
                                            if(match.distance <= 0.5) {{ 
                                                status.style.display = "none";
                                                document.getElementById('kode').style.display = "inline-block";
                                                
                                                try {{
                                                    const btns = window.parent.document.querySelectorAll('button');
                                                    btns.forEach(btn => {{
                                                        if(btn.innerText.includes("MASUK") || btn.innerText.includes("PULANG")) {{
                                                            btn.style.pointerEvents = "auto";
                                                            btn.style.opacity = "1";
                                                            btn.style.filter = "none";
                                                        }}
                                                    }});
                                                }} catch(err) {{}}
                                                
                                            }} else {{ status.innerText = "⛔ WAJAH TIDAK COCOK!"; }}
                                        }} catch(e) {{ status.innerText = "Gagal memuat sistem verifikasi AI."; }}
                                    }}
                                    setTimeout(runAI, 500);
                                </script>
                            </body>
                            </html>
                            """
                            components.html(html_code, height=60, scrolling=False)
                            
                            # Kunci tombol sementara
                            components.html("""
                                <script>
                                try {
                                    const btns = window.parent.document.querySelectorAll('button');
                                    btns.forEach(btn => {
                                        if(btn.innerText.includes("MASUK") || btn.innerText.includes("PULANG")) {
                                            btn.style.pointerEvents = "none";
                                            btn.style.opacity = "0.3";
                                            btn.style.filter = "grayscale(100%)";
                                        }
                                    });
                                } catch(err) {}
                                </script>
                            """, height=0, width=0)
                            
                        else:
                            # ==========================================
                            # LOGIKA 2: PEGAWAI CADAR (BYPASS AI)
                            # ==========================================
                            st.info("🧕 **Akun Terotorisasi:** Verifikasi biometrik dilewati. Kehadiran divalidasi melalui GPS dan Foto Bukti.")

                        # --- TOMBOL PRESENSI ---
                        col_masuk, col_pulang = st.columns(2)
                        with col_masuk:
                            btn_masuk = st.button("📥 MASUK", type="primary", width="stretch")
                        with col_pulang:
                            btn_pulang = st.button("📤 PULANG", width="stretch")
                            
                        if btn_masuk or btn_pulang:
                            now = datetime.datetime.now(pytz.timezone('Asia/Makassar'))
                            tgl_sekarang = now.strftime('%Y-%m-%d')
                            jenis_aksi = "Masuk" if btn_masuk else "Pulang"
                            
                            # 🚀 OPTIMASI: Hanya tarik data pegawai ini di tanggal ini langsung dari Supabase
                            try:
                                res_absen = supabase.table('absensi').select('status').eq('nip', str(emp_data['nip'])).eq('tanggal', tgl_sekarang).execute()
                                df_absen_hari_ini = pd.DataFrame(res_absen.data) if res_absen.data else pd.DataFrame()
                            except Exception:
                                df_absen_hari_ini = pd.DataFrame()
                            
                            sudah_absen = False
                            if not df_absen_hari_ini.empty and 'status' in df_absen_hari_ini.columns:
                                data_terceklis = df_absen_hari_ini[
                                    df_absen_hari_ini['status'].str.contains(jenis_aksi, na=False, case=False)
                                ]
                                if not data_terceklis.empty:
                                    sudah_absen = True

                            if sudah_absen:
                                st.warning(f"⚠️ Anda sudah melakukan absensi **{jenis_aksi}** untuk hari ini ({tgl_sekarang})!")
                            else:
                                jam_sekarang = now.time()
                                st.session_state.settings = get_data_pengaturan()
                                
                                batas_masuk_str = st.session_state.settings['batas_masuk'].iloc[0]
                                batas_pulang_str = st.session_state.settings['batas_pulang'].iloc[0]
                                
                                batas_masuk_obj = datetime.datetime.strptime(batas_masuk_str, '%H:%M').time()
                                batas_pulang_obj = datetime.datetime.strptime(batas_pulang_str, '%H:%M').time()
                                
                                if btn_masuk:
                                    jenis_absen = "Masuk (TERLAMBAT)" if jam_sekarang > batas_masuk_obj else "Masuk (Tepat Waktu)"
                                else:
                                    jenis_absen = "Pulang (LEBIH AWAL)" if jam_sekarang < batas_pulang_obj else "Pulang (Tepat Waktu)"

                                status_final = f'Hadir - {jenis_absen}'
                                if is_cadar:
                                    status_final = f'Hadir [Audit Manual] - {jenis_absen}'

                                data_absen_baru = {
                                    'nip': str(emp_data['nip']), 
                                    'nama': emp_data['name'], 
                                    'sekolah': sch_data['school_name'],
                                    'tanggal': tgl_sekarang, 
                                    'jam': now.strftime('%H:%M:%S'),
                                    'jarak_m': str(round(jarak_meter, 1)), 
                                    'status': status_final,
                                    'foto_bukti': cam_base64 # Simpan foto bukti di database
                                }
                                
                                supabase.table('absensi').insert(data_absen_baru).execute()
                                st.success(f"✅ Absensi {jenis_absen} Anda berhasil tersimpan!")
            else:
                st.error(f"⛔ Akses Ditolak! Jarak Anda {jarak_meter:.0f} meter. Anda berada di luar radius {sch_data['radius_m']} meter.")
        else:
            st.warning("Menunggu akses GPS. Mohon izinkan lokasi di browser.")

# ==========================================
# HAK AKSES 2: ADMIN
# ==========================================
elif st.session_state.role == "Admin":
    col_judul, col_tombol = st.columns([3, 1])
    with col_judul:
        st.title("🔐 Dashboard Admin")
    with col_tombol:
        st.button("🚪 Logout", on_click=logout, width="stretch")
    
    st.session_state.employees = get_data_pegawai()
    st.session_state.schools = get_data_sekolah()
    
    if st.session_state.employees.empty:
         st.warning("Belum ada data pegawai. Minta Superadmin menambah pegawai terlebih dahulu.")
    else:
        st.markdown("### 📸 1. Kelola Foto Acuan Pegawai")
        
        opsi_sekolah_foto = ["Semua Sekolah"] + st.session_state.schools['school_name'].tolist()
        sekolah_pilihan_foto = st.selectbox("🏢 Filter Sekolah:", opsi_sekolah_foto, key="filter_sekolah_foto")
        
        df_kandidat = st.session_state.employees.copy()
        if sekolah_pilihan_foto != "Semua Sekolah":
            df_kandidat = df_kandidat[df_kandidat['school_name'] == sekolah_pilihan_foto]
            
        total_pegawai = len(df_kandidat)
        
        if total_pegawai == 0:
            st.info("Tidak ada pegawai di sekolah ini.")
        else:
            items_per_page = 10
            total_pages = (total_pegawai // items_per_page) + (1 if total_pegawai % items_per_page > 0 else 0)
            
            col_info, col_page = st.columns([1, 1])
            with col_info:
                st.caption(f"Menampilkan total {total_pegawai} pegawai.")
                
            with col_page:
                if total_pages > 1:
                    page = st.selectbox("📄 Pilih Halaman:", range(1, total_pages + 1), format_func=lambda x: f"Halaman {x} dari {total_pages}")
                else:
                    page = 1
                    
            start_idx = (page - 1) * items_per_page
            end_idx = start_idx + items_per_page
            df_page = df_kandidat.iloc[start_idx:end_idx]
            
            st.write("---")
            
            for index, emp in df_page.iterrows():
                nip = str(emp['nip'])
                nama = emp['name']
                sekolah_emp = emp['school_name']
                is_cadar = str(emp.get('is_cadar', 'False')).lower() == 'true'
                
                is_uploaded = str(emp.get('photo_uploaded', False)).lower() == 'true'
                status_simbol = "🧕" if is_cadar else ("🟢" if is_uploaded else "🔴")
                status_teks = "Mode Cadar (Audit)" if is_cadar else ""
                
                with st.expander(f"{status_simbol} {nama} — NIP: {nip} {status_teks}"):
                    col_kiri, col_kanan = st.columns([1, 2])
                    
                    with col_kiri:
                        if is_uploaded and pd.notna(emp.get('photo_base64')) and emp['photo_base64'] != '':
                            st.image(emp['photo_base64'], caption="Foto Saat Ini", use_container_width=True)
                        else:
                            st.info("📷 Belum ada foto")
                            
                    with col_kanan:
                        st.markdown(f"**Unit Kerja:** {sekolah_emp}")
                        if is_uploaded:
                            st.warning("⚠️ Mengunggah foto baru akan menimpa foto lama.")
                        
                        foto = st.file_uploader("Pilih Pas Foto Baru", type=['jpg', 'jpeg', 'png'], key=f"foto_{nip}")
                        
                        if foto and st.button("💾 Simpan & Update Foto", type="primary", key=f"btn_{nip}", use_container_width=True):
                            base64_str = base64.b64encode(foto.getvalue()).decode('utf-8')
                            full_base64 = f"data:image/jpeg;base64,{base64_str}"
                            
                            supabase.table('pegawai').update({
                                'photo_uploaded': True,
                                'photo_base64': full_base64
                            }).eq('nip', nip).execute()
                            
                            st.success("✅ Foto berhasil diperbarui!")
                            st.session_state.employees = get_data_pegawai()
                            time.sleep(1)
                            st.rerun()

    st.markdown("### 2. Laporan & Rekap Absensi")
    
    col_tgl, col_sch = st.columns(2)
    with col_tgl:
        tgl_pilihan = st.date_input("Pilih Tanggal Rekap:", datetime.datetime.now(pytz.timezone('Asia/Makassar')).date())
    with col_sch:
        opsi_sekolah = ["Semua Sekolah"] + st.session_state.schools['school_name'].tolist()
        sekolah_pilihan = st.selectbox("Filter Sekolah:", opsi_sekolah)
    
    df_emp = st.session_state.employees.copy()
    if sekolah_pilihan != "Semua Sekolah":
        df_emp = df_emp[df_emp['school_name'] == sekolah_pilihan]
        
    if df_emp.empty:
        st.warning(f"Tidak ada pegawai terdaftar pada unit {sekolah_pilihan}.")
    else:
        tgl_str = tgl_pilihan.strftime('%Y-%m-%d')
        
        # 🚀 OPTIMASI: Hanya tarik data dari Supabase yang tanggalnya cocok dengan pilihan Admin
        try:
            res_absen_admin = supabase.table('absensi').select('*').eq('tanggal', tgl_str).execute()
            if res_absen_admin.data:
                df_absen_tgl = pd.DataFrame(res_absen_admin.data)
                if 'nip' in df_absen_tgl.columns:
                    df_absen_tgl['nip'] = df_absen_tgl['nip'].astype(str)
            else:
                df_absen_tgl = pd.DataFrame(columns=['nip', 'nama', 'sekolah', 'tanggal', 'jam', 'jarak_m', 'status'])
        except Exception:
            df_absen_tgl = pd.DataFrame(columns=['nip', 'nama', 'sekolah', 'tanggal', 'jam', 'jarak_m', 'status'])
        
        rekap_list = []
        for index, emp in df_emp.iterrows():
            nip = str(emp['nip'])
            nama = emp['name']
            sekolah = emp['school_name']
            
            data_absen_pegawai = df_absen_tgl[df_absen_tgl['nip'] == nip]
            
            jam_masuk = '-'
            jam_pulang = '-'
            jarak = '-'
            status_final = 'Tanpa Keterangan'
            
            if not data_absen_pegawai.empty:
                absen_masuk = data_absen_pegawai[data_absen_pegawai['status'].str.contains('Masuk', na=False, case=False)]
                if not absen_masuk.empty:
                    jam_masuk = absen_masuk.iloc[0]['jam']
                    jarak = absen_masuk.iloc[0]['jarak_m']
                    status_final = absen_masuk.iloc[0]['status']
                
                absen_pulang = data_absen_pegawai[data_absen_pegawai['status'].str.contains('Pulang', na=False, case=False)]
                if not absen_pulang.empty:
                    jam_pulang = absen_pulang.iloc[0]['jam']
                    if jarak == '-':
                        jarak = absen_pulang.iloc[0]['jarak_m']
                    
                    if not absen_masuk.empty:
                        status_final = f"{absen_masuk.iloc[0]['status']} & {absen_pulang.iloc[0]['status']}"
                    else:
                        status_final = absen_pulang.iloc[0]['status']
                
                absen_lainnya = data_absen_pegawai[~data_absen_pegawai['status'].str.contains('Hadir|Masuk|Pulang', na=False, case=False)]
                if not absen_lainnya.empty:
                    status_final = absen_lainnya.iloc[0]['status']
                    jarak = absen_lainnya.iloc[0]['jarak_m']
                    
            rekap_list.append({
                'NIP': nip,
                'NAMA': nama,
                'SEKOLAH': sekolah,
                'TANGGAL': tgl_str,
                'JARAK': str(jarak),
                'MASUK': jam_masuk,
                'PULANG': jam_pulang,
                'STATUS': status_final
            })
            
        df_rekap = pd.DataFrame(rekap_list)
        
        total_pegawai = len(df_rekap)
        hadir_count = len(df_rekap[df_rekap['STATUS'].str.contains('Hadir|Masuk|Pulang', na=False)])
        tanpa_ket_count = len(df_rekap[df_rekap['STATUS'] == 'Tanpa Keterangan'])
        izin_dll_count = total_pegawai - hadir_count - tanpa_ket_count
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Pegawai", total_pegawai)
        m2.metric("Hadir", hadir_count)
        m3.metric("Izin/Sakit/Cuti/Dinas", izin_dll_count)
        m4.metric("Tanpa Keterangan", tanpa_ket_count)
        
        def warnai_status(val):
            if isinstance(val, str):
                if 'TERLAMBAT' in val or 'LEBIH AWAL' in val:
                    return 'color: #D9534F; font-weight: bold;'
                elif 'Tepat Waktu' in val:
                    return 'color: #5CB85C; font-weight: bold;'
                elif 'Audit' in val:
                    return 'color: #0275d8; font-style: italic;'
                elif val == 'Tanpa Keterangan':
                    return 'color: #F0AD4E;'
            return ''

        df_berwarna = df_rekap.style.map(warnai_status, subset=['STATUS'])
        
        st.dataframe(df_berwarna, width="stretch")
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
            df_rekap.to_excel(writer, index=False, sheet_name='Rekap Absensi')
            
        st.download_button(
            label="📥 Download Rekap Absensi (Excel)",
            data=buffer.getvalue(),
            file_name=f"Rekap_Absensi_{sekolah_pilihan.replace(' ', '_')}_{tgl_str}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

# ==========================================
# HAK AKSES 3: SUPERADMIN
# ==========================================
elif st.session_state.role == "Superadmin":
    col_judul, col_tombol = st.columns([3, 1])
    with col_judul:
        st.title("🛠️ Dashboard Superadmin")
    with col_tombol:
        st.button("🚪 Logout", on_click=logout, width="stretch")
    
    st.session_state.schools = get_data_sekolah()
    st.session_state.employees = get_data_pegawai()
    st.session_state.settings = get_data_pengaturan()
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "🏛️ Kelola Sekolah", 
        "👥 Kelola Pegawai", 
        "🔑 Kelola Admin", 
        "📝 Input Izin/Dinas", 
        "🚨 Database", 
        "⚙️ Jam Kerja"
    ])
    
    with tab1:
        st.markdown("### Tambah Titik Sekolah Baru")
        st.info("Buka Google Maps, klik kanan pada lokasi sekolah, salin angka koordinatnya.")
        with st.form("form_sekolah"):
            new_sch_name = st.text_input("Nama Sekolah / Area Lokasi")
            col_lat, col_lng = st.columns(2)
            with col_lat:
                new_lat = st.number_input("Latitude (Cth: -5.147665)", format="%.6f")
            with col_lng:
                new_lng = st.number_input("Longitude (Cth: 119.432731)", format="%.6f")
            new_rad = st.number_input("Radius Akses (Meter)", min_value=10, value=100)
            
            if st.form_submit_button("Simpan Sekolah Baru"):
                if new_sch_name:
                    data_sekolah_baru = {
                        'school_name': new_sch_name, 
                        'lat': new_lat, 
                        'lng': new_lng, 
                        'radius_m': new_rad
                    }
                    supabase.table('sekolah').insert(data_sekolah_baru).execute()
                    st.session_state.schools = get_data_sekolah()
                    st.success(f"Sekolah {new_sch_name} berhasil ditambahkan!")
                    st.rerun()
                else:
                    st.error("Nama sekolah tidak boleh kosong.")
                    
        st.write("---")
        st.markdown("### ✏️ Edit & Kelola Sekolah Aktif")
        st.info("💡 **Cara Edit:** Klik dua kali sel tabel untuk mengubah angka. **Cara Hapus:** Centang kotak di sisi kiri tabel, lalu tekan tempat sampah. **WAJIB** klik Simpan Perubahan di bawah.")
        
        edited_schools = st.data_editor(
            st.session_state.schools,
            num_rows="dynamic",
            width="stretch",
            key="school_editor"
        )
        
        if st.button("💾 Simpan Perubahan Tabel", type="primary"):
            supabase.table('sekolah').delete().neq('school_name', '').execute()
            records = edited_schools.to_dict(orient='records')
            if records:
                supabase.table('sekolah').insert(records).execute()
            st.session_state.schools = get_data_sekolah()
            st.success("Perubahan data sekolah berhasil disimpan secara permanen!")
            st.rerun()

    with tab2:
        st.markdown("### 1. Tambah Pegawai (Manual)")
        with st.form("form_tambah_pegawai"):
            new_nip = st.text_input("NIP")
            new_name = st.text_input("Nama Lengkap")
            opsi_sekolah_input = st.session_state.schools['school_name'].tolist() if not st.session_state.schools.empty else []
            new_school = st.selectbox("Penempatan Sekolah", opsi_sekolah_input)
            
            if st.form_submit_button("Tambahkan Manual"):
                if new_nip and new_name:
                    data_pegawai_baru = {
                        'nip': str(new_nip),
                        'name': new_name,
                        'school_name': new_school,
                        'photo_uploaded': False,
                        'photo_base64': '',
                        'is_cadar': False
                    }
                    supabase.table('pegawai').insert(data_pegawai_baru).execute()
                    st.session_state.employees = get_data_pegawai()
                    st.success(f"Pegawai ditambahkan ke {new_school}!")
                    st.rerun()
                else:
                    st.error("NIP dan Nama Pegawai wajib diisi.")
        
        st.write("---")
        st.markdown("### 2. Tambah Pegawai (Upload Excel/CSV Massal)")
        
        template_df = pd.DataFrame({
            'nip': ['198001012005011001', '198203042008012003'],
            'name': ['Ahmad Guru', 'Siti Pengajar'],
            'school_name': ['Sekolah Default', 'Sekolah Default']
        })
        csv_template = template_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 1. Download Template CSV", data=csv_template, file_name="Template_Data_Pegawai.csv", mime="text/csv")
        
        file_upload = st.file_uploader("2. Upload File Template yang sudah diisi", type=['csv'])
        if file_upload is not None:
            if st.button("Proses Upload"):
                try:
                    df_upload = pd.read_csv(file_upload)
                    if all(col in df_upload.columns for col in ['nip', 'name', 'school_name']):
                        df_upload['photo_uploaded'] = False
                        df_upload['photo_base64'] = ''
                        df_upload['is_cadar'] = False
                        df_upload['nip'] = df_upload['nip'].astype(str)
                        
                        records = df_upload.to_dict(orient='records')
                        supabase.table('pegawai').upsert(records, on_conflict='nip').execute()
                        st.session_state.employees = get_data_pegawai()
                        
                        st.success(f"Berhasil mengunggah {len(df_upload)} data pegawai!")
                        st.rerun()
                    else:
                        st.error("Format kolom salah! Pastikan file memiliki kolom: nip, name, school_name.")
                except Exception as e:
                    st.error(f"Gagal membaca file: {e}")

        st.write("---")
        st.markdown("### 📋 Edit & Kelola Daftar Pegawai Aktif")
        
        # --- PERUBAHAN: MENAMBAHKAN KOLOM PENCARIAN ---
        col_f1, col_f2 = st.columns(2)
        
        with col_f1:
            opsi_sekolah_filter = ["Semua Sekolah"]
            if not st.session_state.schools.empty:
                opsi_sekolah_filter += st.session_state.schools['school_name'].tolist()
            sekolah_pilihan_peg = st.selectbox("🏢 Filter Sekolah:", opsi_sekolah_filter, key="filter_sekolah_pegawai")
            
        with col_f2:
            search_query = st.text_input("🔍 Cari NIP atau Nama:", placeholder="Ketik NIP atau Nama...", key="search_pegawai")
        
        df_peg_filtered = st.session_state.employees.copy()
        
        # 1. Terapkan filter sekolah
        if sekolah_pilihan_peg != "Semua Sekolah":
            df_peg_filtered = df_peg_filtered[df_peg_filtered['school_name'] == sekolah_pilihan_peg]
            
        # 2. Terapkan filter pencarian teks (NIP atau Nama)
        if search_query:
            mask_search = (
                df_peg_filtered['nip'].astype(str).str.contains(search_query, case=False, na=False) | 
                df_peg_filtered['name'].astype(str).str.contains(search_query, case=False, na=False)
            )
            df_peg_filtered = df_peg_filtered[mask_search]
            
        total_peg = len(df_peg_filtered)
        
        if total_peg == 0:
            st.info("Tidak ada data pegawai yang ditemukan sesuai filter/pencarian Anda.")
        else:
            items_per_page = 10
            # ... (Lanjutkan dengan sisa kode pagination dan expander seperti sebelumnya)
            total_pages = (total_peg // items_per_page) + (1 if total_peg % items_per_page > 0 else 0)
            
            col_info, col_page = st.columns([1, 1])
            with col_info:
                st.caption(f"Menampilkan total **{total_peg}** pegawai.")
            with col_page:
                if total_pages > 1:
                    page_peg = st.selectbox("📄 Halaman:", range(1, total_pages + 1), format_func=lambda x: f"Halaman {x} dari {total_pages}", key="page_pegawai")
                else:
                    page_peg = 1
                
            start_idx = (page_peg - 1) * items_per_page
            end_idx = start_idx + items_per_page
            df_page_peg = df_peg_filtered.iloc[start_idx:end_idx]
            
            for idx, emp in df_page_peg.iterrows():
                nip_old = str(emp['nip'])
                nama_old = emp['name']
                sekolah_old = emp['school_name']
                is_uploaded = str(emp.get('photo_uploaded', False)).lower() == 'true'
                is_cadar_old = str(emp.get('is_cadar', False)).lower() == 'true'
                
                status_kunci = "🔒 Foto Terkunci" if is_uploaded else "🔓 Foto Belum Diunggah"
                if is_cadar_old:
                    status_kunci += " (🧕 Mode Cadar Aktif)"
                
                with st.expander(f"👤 {nama_old} — NIP: {nip_old} ({status_kunci})"):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        edit_nip = st.text_input("NIP Pegawai", value=nip_old, key=f"nip_edit_{nip_old}")
                        edit_nama = st.text_input("Nama Pegawai", value=nama_old, key=f"nama_edit_{nip_old}")
                        
                        # Tambahan Toggle Mode Cadar di Superadmin
                        edit_cadar = st.checkbox("🧕 Izinkan Mode Cadar (Bypass AI)", value=is_cadar_old, key=f"cadar_edit_{nip_old}")
                        
                    with col_e2:
                        list_sch = st.session_state.schools['school_name'].tolist() if not st.session_state.schools.empty else [sekolah_old]
                        default_sch_idx = list_sch.index(sekolah_old) if sekolah_old in list_sch else 0
                        edit_sekolah = st.selectbox("Penempatan Sekolah", list_sch, index=default_sch_idx, key=f"sch_edit_{nip_old}")
                        
                        st.markdown("**Status Foto Verifikasi:**")
                        if is_uploaded:
                            st.warning("Foto acuan sudah diunggah oleh Admin.")
                            if st.button("🔓 Buka Kunci Foto (Reset Foto)", key=f"unlock_foto_{nip_old}", use_container_width=True):
                                supabase.table('pegawai').update({
                                    'photo_uploaded': False,
                                    'photo_base64': ''
                                }).eq('nip', nip_old).execute()
                                
                                st.session_state.employees = get_data_pegawai()
                                st.success(f"✅ Kunci foto pegawai {nama_old} berhasil dibuka!")
                                time.sleep(1)
                                st.rerun()
                        else:
                            st.info("Belum ada foto acuan (Siap diunggah oleh Admin).")
                            
                    col_btn1, col_btn2 = st.columns(2)
                    with col_btn1:
                        if st.button("💾 Simpan Perubahan Data", key=f"save_peg_{nip_old}", type="primary", use_container_width=True):
                            supabase.table('pegawai').update({
                                'nip': str(edit_nip),
                                'name': edit_nama,
                                'school_name': edit_sekolah,
                                'is_cadar': edit_cadar
                            }).eq('nip', nip_old).execute()
                            
                            st.session_state.employees = get_data_pegawai()
                            st.success(f"✅ Data {edit_nama} berhasil diperbarui!")
                            time.sleep(1)
                            st.rerun()
                            
                    with col_btn2:
                        if st.button("🗑️ Hapus Pegawai", key=f"del_peg_{nip_old}", use_container_width=True):
                            supabase.table('pegawai').delete().eq('nip', nip_old).execute()
                            st.session_state.employees = get_data_pegawai()
                            st.success(f"🗑️ Pegawai {nama_old} berhasil dihapus!")
                            time.sleep(1)
                            st.rerun()

    with tab3:
        st.markdown("### 🔑 Kelola Akun Admin")
        
        with st.form("form_tambah_admin"):
            st.markdown("##### ➕ Tambah Akun Admin Baru")
            new_admin_user = st.text_input("Username Admin")
            new_admin_pass = st.text_input("Password Admin", type="password")
            
            opsi_sekolah_admin = ["Semua Sekolah"]
            if not st.session_state.schools.empty:
                opsi_sekolah_admin += st.session_state.schools['school_name'].tolist()
                
            new_admin_school = st.selectbox("Akses Sekolah / Unit Kerja", opsi_sekolah_admin)
            
            if st.form_submit_button("➕ Simpan Akun Admin Baru", type="primary"):
                if new_admin_user and new_admin_pass:
                    data_admin_baru = {
                        'username': new_admin_user,
                        'password': new_admin_pass,
                        'sekolah': new_admin_school
                    }
                    supabase.table('admins').insert(data_admin_baru).execute()
                    st.success(f"✅ Akun Admin '{new_admin_user}' berhasil ditambahkan!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("⚠️ Username dan Password wajib diisi.")
                    
        st.write("---")
        st.markdown("### 📋 Daftar Akun Admin Aktif")
        
        df_admins = get_data_admin()
        
        if df_admins.empty:
            st.info("Belum ada akun admin tersimpan di database.")
        else:
            for idx, row in df_admins.iterrows():
                admin_id = row.get('id')
                username = row.get('username', '')
                sekolah = row.get('sekolah', 'Semua Sekolah')
                
                with st.expander(f"👤 {username} — Unit Kerja: {sekolah}"):
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        edit_user = st.text_input("Username", value=str(username), key=f"usr_{idx}")
                        edit_pass = st.text_input("Password Baru", value=str(row.get('password', '')), type="password", key=f"pwd_{idx}")
                    with col_e2:
                        default_idx = opsi_sekolah_admin.index(sekolah) if sekolah in opsi_sekolah_admin else 0
                        edit_sch = st.selectbox("Akses Sekolah", opsi_sekolah_admin, index=default_idx, key=f"sch_{idx}")
                        
                    col_b1, col_b2 = st.columns(2)
                    with col_b1:
                        if st.button("💾 Simpan Perubahan", key=f"save_adm_{idx}", type="primary", use_container_width=True):
                            query = supabase.table('admins').update({
                                'username': edit_user,
                                'password': edit_pass,
                                'sekolah': edit_sch
                            })
                            if pd.notna(admin_id):
                                query = query.eq('id', admin_id)
                            else:
                                query = query.eq('username', username)
                            query.execute()
                            st.success(f"✅ Akun '{edit_user}' berhasil diperbarui!")
                            time.sleep(1)
                            st.rerun()
                            
                    with col_b2:
                        if st.button("🗑️ Hapus Akun Admin", key=f"del_adm_{idx}", use_container_width=True):
                            query = supabase.table('admins').delete()
                            if pd.notna(admin_id):
                                query = query.eq('id', admin_id)
                            else:
                                query = query.eq('username', username)
                            query.execute()
                            st.success(f"🗑️ Akun admin '{username}' berhasil dihapus!")
                            time.sleep(1)
                            st.rerun()

    with tab4:
        st.markdown("### 📝 Input Keterangan Absensi (Manual)")
        
        if st.session_state.employees.empty:
            st.warning("Belum ada data pegawai.")
        else:
            with st.form("form_izin"):
                pilihan_pegawai = st.selectbox("Pilih Pegawai:", st.session_state.employees['name'].tolist())
                jenis_absen = st.selectbox("Status Kehadiran:", ["Sakit", "Izin", "Cuti", "Dinas Luar"])
                
                col_tgl1, col_tgl2 = st.columns(2)
                with col_tgl1:
                    tanggal_mulai = st.date_input("Dari Tanggal")
                with col_tgl2:
                    tanggal_selesai = st.date_input("Sampai Tanggal")
                    
                file_surat = st.file_uploader("Upload Bukti Surat (PDF/JPG/PNG)", type=['pdf', 'jpg', 'jpeg', 'png'])
                
                if st.form_submit_button("Simpan Data Absensi"):
                    if tanggal_selesai < tanggal_mulai:
                        st.error("Error: 'Sampai Tanggal' tidak boleh lebih awal dari 'Dari Tanggal'.")
                    elif file_surat is not None:
                        emp_data = st.session_state.employees[st.session_state.employees['name'] == pilihan_pegawai].iloc[0]
                        file_ext = file_surat.name.split('.')[-1]
                        file_name = f"{emp_data['nip']}_{jenis_absen}_{tanggal_mulai.strftime('%Y%m%d')}_sd_{tanggal_selesai.strftime('%Y%m%d')}.{file_ext}"
                        file_path = os.path.join(DIR_SURAT, file_name)
                        
                        with open(file_path, "wb") as f:
                            f.write(file_surat.getbuffer())
                        
                        delta = tanggal_selesai - tanggal_mulai
                        daftar_tanggal = [tanggal_mulai + datetime.timedelta(days=i) for i in range(delta.days + 1)]
                        
                        list_absen = []
                        for tgl in daftar_tanggal:
                            list_absen.append({
                                'nip': str(emp_data['nip']), 
                                'nama': emp_data['name'], 
                                'sekolah': emp_data['school_name'],
                                'tanggal': tgl.strftime('%Y-%m-%d'), 
                                'jam': '-',
                                'jarak_m': 'Dilampirkan Surat', 
                                'status': jenis_absen,
                                'foto_bukti': ''
                            })
                            
                        supabase.table('absensi').insert(list_absen).execute()
                        st.success(f"Berhasil! Absensi {jenis_absen} untuk {pilihan_pegawai} dari {tanggal_mulai.strftime('%d-%m-%Y')} s/d {tanggal_selesai.strftime('%d-%m-%Y')} telah tercatat.")
                    else:
                        st.error("Harap unggah file bukti surat terlebih dahulu sebelum menyimpan.")
                        
    with tab5:
        st.markdown("### Reset Data Sistem")
        st.warning("Perhatian! Menghapus data di sini tidak dapat dikembalikan.")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🗑️ Kosongkan Data Absensi"):
                supabase.table('absensi').delete().neq('nip', '').execute()
                st.success("Tabel absensi di database dibersihkan!")
        with col2:
            if st.button("🚨 Reset Semua Pegawai"):
                supabase.table('pegawai').delete().neq('nip', '').execute()
                st.session_state.employees = pd.DataFrame()
                st.success("Data pegawai telah di-reset!")

    with tab6:
        st.markdown("### ⚙️ Pengaturan Batas Waktu Absensi")
        
        waktu_masuk_str = st.session_state.settings['batas_masuk'].iloc[0]
        waktu_pulang_str = st.session_state.settings['batas_pulang'].iloc[0]
        
        waktu_masuk_obj = datetime.datetime.strptime(waktu_masuk_str, '%H:%M').time()
        waktu_pulang_obj = datetime.datetime.strptime(waktu_pulang_str, '%H:%M').time()
        
        with st.form("form_waktu"):
            new_batas_masuk = st.time_input("Batas Waktu Absen Masuk (Di atas jam ini = Terlambat)", waktu_masuk_obj)
            new_batas_pulang = st.time_input("Batas Waktu Absen Pulang (Di bawah jam ini = Pulang Awal)", waktu_pulang_obj)
            
            if st.form_submit_button("Simpan Pengaturan Waktu", type="primary"):
                batas_masuk_format = new_batas_masuk.strftime('%H:%M')
                batas_pulang_format = new_batas_pulang.strftime('%H:%M')
                
                supabase.table('pengaturan').update({
                    'batas_masuk': batas_masuk_format,
                    'batas_pulang': batas_pulang_format
                }).neq('batas_masuk', '').execute()
                
                st.session_state.settings = get_data_pengaturan()
                st.success("✅ Pengaturan waktu berhasil disimpan dan akan berlaku untuk seluruh sekolah.")
                time.sleep(1)
                st.rerun()
