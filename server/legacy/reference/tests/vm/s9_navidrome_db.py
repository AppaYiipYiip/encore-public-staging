import shutil, sqlite3, tempfile, os, glob
src = os.path.expanduser("~/encore-server/data/navidrome")
tmp = tempfile.mkdtemp()
for f in glob.glob(src + "/navidrome.db*"):
    shutil.copy(f, tmp)
c = sqlite3.connect(os.path.join(tmp, "navidrome.db"))
print("tables:", [r[0] for r in c.execute("select name from sqlite_master where type='table' order by name")][:60])
for t in ("annotation", "user", "scrobbles", "playlist", "playlist_tracks"):
    try:
        cols = [r[1] for r in c.execute(f"pragma table_info({t})")]
        n = c.execute(f"select count(*) from {t}").fetchone()[0]
        print(t, n, cols)
    except Exception as e:
        print(t, "ERR", e)
print("--- annotation sample")
for r in c.execute("select user_id, item_id, item_type, play_count, play_date, starred, starred_at, rating from annotation limit 8"):
    print(r)
print("--- users"); 
for r in c.execute("select id, user_name, is_admin, last_access_at from user"): print(r)
print("--- media_file cols:", [r[1] for r in c.execute("pragma table_info(media_file)")][:50])
print("--- artist cols:", [r[1] for r in c.execute("pragma table_info(artist)")][:30])
