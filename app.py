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
            return df
    except Exception:
        pass
    return pd.DataFrame(columns=['nip', 'name', 'school_name', 'photo_uploaded', 'photo_base64'])

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

def get_data_absensi():
    try:
        res = supabase.table('absensi').select('*').execute()
        if res.data:
            df = pd.DataFrame(res.data)
            if 'nip' in df.columns:
                df['nip'] = df['nip'].astype(str)
            return df
    except Exception:
        pass
    return pd.DataFrame(columns=['nip', 'nama', 'sekolah', 'tanggal', 'jam', 'jarak_m', 'status'])

# --- 5. INISIALISASI SESSION STATE ---
if 'schools' not in st.session_state:
    st.session_state.schools = get_data_sekolah()

if 'employees' not in st.session_state:
    st.session_state.employees = get_data_pegawai()

if 'settings' not in st.session_state:
    st.session_state.settings = get_data_pengaturan()

# --- BACA STATUS COOKIE ---
cookie_role = cookie_manager.get(cookie="role")

if 'role' not in st.session_state:
    st.session_state.role = cookie_role

if cookie_role and st.session_state.role != cookie_role:
    st.session_state.role = cookie_role

# --- FUNGSI LOGOUT ---
def logout():
    st.session_state.role = None
    try:
        cookie_manager.delete("role")
    except KeyError:
        pass

# ==========================================
# HALAMAN LOGIN UTAMA
# ==========================================
if st.session_state.role is None:
    st.title("📍 Portal Presensi Terpadu")
    st.info("Selamat datang! Untuk merekam kehadiran Anda, silakan klik tombol di bawah ini.")
    
    if st.button("📸 Mulai Presensi Wajah & GPS", type="primary", width="stretch"):
        st.session_state.role = "Pegawai"
        cookie_manager.set("role", "Pegawai")
        time.sleep(0.5)
        st.rerun()

    st.write("---")
    
    st.caption("Akses khusus Pengelola Sistem:")
    col_admin, col_super = st.columns(2)
    
    with col_admin:
        with st.expander("🔑 Login Admin"):
            pwd = st.text_input("Password Admin:", type="password", key="pwd_admin_main")
            if st.button("Masuk Admin", width="stretch", key="btn_admin_main"):
                if pwd == "admin123":
                    st.session_state.role = "Admin"
                    cookie_manager.set("role", "Admin")
                    time.sleep(0.5)
                    st.rerun()
                else: 
                    st.error("Password Salah!")
                    
    with col_super:
        with st.expander("🛠️ Login Superadmin"):
            pwd_super = st.text_input("Password Superadmin:", type="password", key="pwd_super_main")
            if st.button("Masuk Superadmin", width="stretch", key="btn_super_main"):
                if pwd_super == "superadmin123":
                    st.session_state.role = "Superadmin"
                    cookie_manager.set("role", "Superadmin")
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
                st.markdown("### Rekam Wajah")
                
                is_uploaded = str(emp_data['photo_uploaded']).lower() == 'true'
                
                if is_uploaded and pd.notna(emp_data['photo_base64']):
                    img_camera = st.camera_input("Ambil Foto Wajah Anda")
                    if img_camera:
                        bytes_data = img_camera.getvalue()
                        cam_base64 = f"data:image/jpeg;base64,{base64.b64encode(bytes_data).decode('utf-8')}"
                        
                        html_code = f"""
                        <!DOCTYPE html>
                        <html>
                        <head><script src="https://cdn.jsdelivr.net/npm/@vladmandic/face-api@1.7.12/dist/face-api.js"></script></head>
                        <body style="text-align: center; font-family: sans-serif; margin:0; padding:5px;">
                            <div id="status" style="color:#d9534f; font-weight:bold;">Memuat AI Verifikasi...</div>
                            <div id="kode" style="display:none; color:white; background:#5cb85c; padding:8px 15px; border-radius:5px; font-weight:bold; font-size:18px;">✅ WAJAH COCOK</div>
                            <img id="refImg" src="{emp_data['photo_base64']}" style="display:none;" />
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

                        col_masuk, col_pulang = st.columns(2)
                        with col_masuk:
                            btn_masuk = st.button("📥 MASUK", type="primary", width="stretch")
                        with col_pulang:
                            btn_pulang = st.button("📤 PULANG", width="stretch")
                            
                        if btn_masuk or btn_pulang:
                            now = datetime.datetime.now(pytz.timezone('Asia/Makassar'))
                            tgl_sekarang = now.strftime('%Y-%m-%d')
                            jenis_aksi = "Masuk" if btn_masuk else "Pulang"
                            
                            df_absen = get_data_absensi()
                            
                            sudah_absen = False
                            if not df_absen.empty and 'nip' in df_absen.columns and 'tanggal' in df_absen.columns:
                                data_terceklis = df_absen[
                                    (df_absen['nip'].astype(str) == str(emp_data['nip'])) & 
                                    (df_absen['tanggal'] == tgl_sekarang) & 
                                    (df_absen['status'].str.contains(jenis_aksi, na=False, case=False))
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
                                    if jam_sekarang > batas_masuk_obj:
                                        jenis_absen = "Masuk (TERLAMBAT)"
                                    else:
                                        jenis_absen = "Masuk (Tepat Waktu)"
                                else:
                                    if jam_sekarang < batas_pulang_obj:
                                        jenis_absen = "Pulang (LEBIH AWAL)"
                                    else:
                                        jenis_absen = "Pulang (Tepat Waktu)"

                                data_absen_baru = {
                                    'nip': str(emp_data['nip']), 
                                    'nama': emp_data['name'], 
                                    'sekolah': sch_data['school_name'],
                                    'tanggal': tgl_sekarang, 
                                    'jam': now.strftime('%H:%M:%S'),
                                    'jarak_m': str(round(jarak_meter, 1)), 
                                    'status': f'Hadir - {jenis_absen}'
                                }
                                
                                supabase.table('absensi').insert(data_absen_baru).execute()
                                st.success(f"✅ Absensi {jenis_absen} Anda berhasil tersimpan!")
                else:
                    st.warning("Admin belum mengunggah foto acuan Anda.")
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
        
        # 1. Filter Berdasarkan Sekolah
        opsi_sekolah_foto = ["Semua Sekolah"] + st.session_state.schools['school_name'].tolist()
        sekolah_pilihan_foto = st.selectbox("🏢 Filter Sekolah:", opsi_sekolah_foto, key="filter_sekolah_foto")
        
        # 2. Saring Data Pegawai
        df_kandidat = st.session_state.employees.copy()
        if sekolah_pilihan_foto != "Semua Sekolah":
            df_kandidat = df_kandidat[df_kandidat['school_name'] == sekolah_pilihan_foto]
            
        total_pegawai = len(df_kandidat)
        
        if total_pegawai == 0:
            st.info("Tidak ada pegawai di sekolah ini.")
        else:
            # 3. Sistem Paginasi (10 per halaman)
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
                    
            # 4. Potong Data Sesuai Halaman
            start_idx = (page - 1) * items_per_page
            end_idx = start_idx + items_per_page
            df_page = df_kandidat.iloc[start_idx:end_idx]
            
            st.write("---")
            
            # 5. Tampilan List Expandable Menarik
            for index, emp in df_page.iterrows():
                nip = str(emp['nip'])
                nama = emp['name']
                sekolah_emp = emp['school_name']
                
                # Indikator warna status foto
                is_uploaded = str(emp.get('photo_uploaded', False)).lower() == 'true'
                status_simbol = "🟢" if is_uploaded else "🔴"
                
                with st.expander(f"{status_simbol} {nama} — NIP: {nip}"):
                    # Membagi konten laci menjadi 2 kolom
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
                            # Konversi file ke format Base64
                            base64_str = base64.b64encode(foto.getvalue()).decode('utf-8')
                            full_base64 = f"data:image/jpeg;base64,{base64_str}"
                            
                            # Update tabel pegawai di Supabase
                            supabase.table('pegawai').update({
                                'photo_uploaded': True,
                                'photo_base64': full_base64
                            }).eq('nip', nip).execute()
                            
                            st.success("✅ Foto berhasil diperbarui!")
                            
                            # Refresh data dan halaman
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
        df_absen_raw = get_data_absensi()
        tgl_str = tgl_pilihan.strftime('%Y-%m-%d')
        
        if not df_absen_raw.empty and 'tanggal' in df_absen_raw.columns:
            df_absen_tgl = df_absen_raw[df_absen_raw['tanggal'] == tgl_str]
        else:
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
                elif val == 'Tanpa Keterangan':
                    return 'color: #F0AD4E;'
            return ''

        df_berwarna = df_rekap.style.map(warnai_status, subset=['STATUS'])
        
        st.dataframe(df_berwarna, width="stretch")
        st.download_button(
            "📥 Download Rekap Absensi (CSV)",
            data=df_rekap.to_csv(index=False).encode('utf-8'),
            file_name=f"Rekap_Absensi_{sekolah_pilihan.replace(' ', '_')}_{tgl_str}.csv",
            mime="text/csv"
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
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["🏛️ Kelola Sekolah", "👥 Kelola Pegawai", "📝 Input Izin/Dinas", "🚨 Database", "⚙️ Jam Kerja"])
    
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
            new_school = st.selectbox("Penempatan Sekolah", st.session_state.schools['school_name'].tolist())
            
            if st.form_submit_button("Tambahkan Manual"):
                if new_nip and new_name:
                    data_pegawai_baru = {
                        'nip': str(new_nip),
                        'name': new_name,
                        'school_name': new_school,
                        'photo_uploaded': False,
                        'photo_base64': ''
                    }
                    supabase.table('pegawai').insert(data_pegawai_baru).execute()
                    st.session_state.employees = get_data_pegawai()
                    st.success(f"Pegawai ditambahkan ke {new_school}!")
                    st.rerun()
        
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
        st.markdown("### Daftar Pegawai Aktif")
        if not st.session_state.employees.empty:
            st.dataframe(st.session_state.employees[['nip', 'name', 'school_name', 'photo_uploaded']])

    with tab3:
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
                                'status': jenis_absen
                            })
                            
                        supabase.table('absensi').insert(list_absen).execute()
                        
                        st.success(f"Berhasil! Absensi {jenis_absen} untuk {pilihan_pegawai} dari {tanggal_mulai.strftime('%d-%m-%Y')} s/d {tanggal_selesai.strftime('%d-%m-%Y')} telah tercatat.")
                    else:
                        st.error("Harap unggah file bukti surat terlebih dahulu sebelum menyimpan.")
                        
    with tab4:
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

    with tab5:
        st.markdown("### ⚙️ Pengaturan Batas Waktu Absensi")
        
        waktu_masuk_str = st.session_state.settings['batas_masuk'].iloc[0]
        waktu_pulang_str = st.session_state.settings['batas_pulang'].iloc[0]
        
        waktu_masuk_obj = datetime.datetime.strptime(waktu_masuk_str, '%H:%M').time()
        waktu_pulang_obj = datetime.datetime.strptime(waktu_pulang_str, '%H:%M').time()
        
        with st.form("form_waktu"):
            new_batas_masuk = st.time_input("Batas Waktu Absen Masuk (Di atas jam ini = Terlambat)", waktu_masuk_obj)
            new_batas_pulang = st.time_input("Batas Waktu Absen Pulang (Di bawah jam ini = Pulang Awal)", waktu_pulang_obj)
            
            if st.form_submit_button("Simpan Pengaturan Waktu"):
                updated_settings = {
                    'batas_masuk': new_batas_masuk.strftime('%H:%M'),
                    'batas_pulang': new_batas_pulang.strftime('%H:%M')
                }
                supabase.table('pengaturan').delete().neq('batas_masuk', '').execute()
                supabase.table('pengaturan').insert(updated_settings).execute()
                st.session_state.settings = get_data_pengaturan()
                st.success("✅ Pengaturan jam kerja berhasil diperbarui di database!")
                st.rerun()
