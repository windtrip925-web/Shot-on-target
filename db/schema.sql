-- KARYAWAN AI
CREATE TABLE karyawan (
  id SERIAL PRIMARY KEY,
  kode TEXT UNIQUE NOT NULL,         -- pemburu, perekap, dst
  nama TEXT NOT NULL,
  peran TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Idle'
    CHECK (status IN ('Idle','Bekerja','Selesai','Error')),
  system_prompt TEXT,
  updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO karyawan (kode, nama, peran) VALUES
 ('pemburu','Marwan','Pemburu Isu'),
 ('perekap','Agim','Perekap'),
 ('factcheck','Noval','Fact-Checker'),
 ('penulis','Khotib','Penulis Naskah'),
 ('sutradara','Dede','Sutradara Visual'),
 ('suara','Marno','Pengisi Suara'),
 ('editor','Kadir','Editor Video'),
 ('publisher','Syair','Publisher');

CREATE TABLE tugas_log (
  id BIGSERIAL PRIMARY KEY,
  karyawan_kode TEXT REFERENCES karyawan(kode),
  isu_id INT,
  level TEXT DEFAULT 'info',         -- info, warn, error
  pesan TEXT,
  percobaan INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ISU = pusat alur kerja
CREATE TABLE isu (
  id SERIAL PRIMARY KEY,
  judul TEXT NOT NULL,
  url_sumber TEXT UNIQUE,
  sumber TEXT,
  tanggal_terbit TIMESTAMPTZ,
  skor_viral INT DEFAULT 0,
  tahap TEXT NOT NULL DEFAULT 'baru'
    CHECK (tahap IN ('baru','direkap','dicek','ditulis','disutradarai',
      'disuarakan','diedit','menunggu_persetujuan','disetujui',
      'revisi','ditolak','dipublish','berhenti_disengketakan','error')),
  catatan_owner TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE rekap (
  id SERIAL PRIMARY KEY,
  isu_id INT REFERENCES isu(id) ON DELETE CASCADE,
  fakta_kunci JSONB,       -- [{fakta, sumber, tanggal}]
  ringkasan TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE fakta_check (
  id SERIAL PRIMARY KEY,
  isu_id INT REFERENCES isu(id) ON DELETE CASCADE,
  label TEXT CHECK (label IN ('Terverifikasi','Perlu Dicek','Disengketakan')),
  alasan TEXT,
  detail JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE naskah (
  id SERIAL PRIMARY KEY,
  isu_id INT REFERENCES isu(id) ON DELETE CASCADE,
  versi INT DEFAULT 1,
  hook TEXT,
  isi TEXT,
  durasi_est INT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE adegan (
  id SERIAL PRIMARY KEY,
  naskah_id INT REFERENCES naskah(id) ON DELETE CASCADE,
  urutan INT,
  teks TEXT,
  prompt_visual TEXT,
  footage_path TEXT,
  lisensi TEXT,            -- Pexels / Pixabay / dibuat AI
  durasi_detik NUMERIC
);

CREATE TABLE media (
  id SERIAL PRIMARY KEY,
  isu_id INT REFERENCES isu(id) ON DELETE CASCADE,
  jenis TEXT CHECK (jenis IN ('audio','video','subtitle','thumbnail')),
  path TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE persetujuan (
  id SERIAL PRIMARY KEY,
  isu_id INT REFERENCES isu(id) ON DELETE CASCADE,
  keputusan TEXT CHECK (keputusan IN ('Disetujui','Revisi','Ditolak')),
  catatan TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE akun_sosial (
  id SERIAL PRIMARY KEY,
  platform TEXT CHECK (platform IN ('youtube','instagram','tiktok')),
  nama_akun TEXT,
  token_terenkripsi TEXT,
  aktif BOOLEAN DEFAULT true
);

CREATE TABLE publikasi (
  id SERIAL PRIMARY KEY,
  isu_id INT REFERENCES isu(id),
  platform TEXT,
  caption TEXT,
  hashtag TEXT,
  jadwal TIMESTAMPTZ,
  status TEXT DEFAULT 'terjadwal',   -- terjadwal, terkirim, gagal
  url_post TEXT,
  label_ai BOOLEAN DEFAULT true,
  percobaan INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE statistik (
  id SERIAL PRIMARY KEY,
  publikasi_id INT REFERENCES publikasi(id) ON DELETE CASCADE,
  views INT DEFAULT 0, likes INT DEFAULT 0,
  komentar INT DEFAULT 0, shares INT DEFAULT 0,
  diambil_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE pengaturan (
  kunci TEXT PRIMARY KEY,
  nilai JSONB
);
INSERT INTO pengaturan VALUES
 ('gaya_bahasa','"Indonesia absurd, santai, lucu, akurat, tanpa tuduhan tak berdasar"'),
 ('jam_posting','["12:00","18:00"]');

-- Tanggal merah & cuti bersama tambahan (di luar kalender bawaan)
CREATE TABLE libur_tambahan (
  tanggal DATE PRIMARY KEY,
  keterangan TEXT
);