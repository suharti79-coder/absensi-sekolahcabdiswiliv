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
                            # Konversi file ke format Base64 (sesuai standar app.py Anda)
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
