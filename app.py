from datetime import date
from typing import List
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import database as db

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
def startup():
    db.init_db()

@app.get("/", response_class=HTMLResponse)
def index(
    request: Request,
    tab: str = "register",
    filter: str = "all",
    edit_id: int = None,
    h2h_p1: str = "TH",
    h2h_p2: str = "KH"
):
    leaderboard, highlights = db.calculate_stats(filter_type=filter)
    matches = db.get_all_matches()
    edit_match = db.get_match_by_id(edit_id) if edit_id else None
    h2h_data = db.get_head_to_head_stats(h2h_p1, h2h_p2)

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_tab": tab,
            "filter": filter,
            "today": date.today().isoformat(),
            "players": db.PLAYERS,
            "leaderboard": leaderboard,
            "highlights": highlights,
            "matches": matches,
            "edit_match": edit_match,
            "h2h": h2h_data,
            "h2h_p1": h2h_p1,
            "h2h_p2": h2h_p2
        },
    )
    
@app.post("/matches/new")
def create_match(
    match_date: str = Form(...),
    match_preset: str = Form(...),
    single_custom_t1: str = Form(None),
    single_custom_t2: str = Form(None),
    guest_t1: str = Form(None),
    guest_t2: str = Form(None),
    s1_1: int = Form(...), s1_2: int = Form(...),
    s2_1: int = Form(...), s2_2: int = Form(...),
    s3_1: int = Form(...), s3_2: int = Form(...),
    s4_1: int = Form(None), s4_2: int = Form(None),
    s5_1: int = Form(None), s5_2: int = Form(None),
):
    # Udled hold, type og antal obligatoriske sæt
    target_sets = 3
    match_type = "single"

    if match_preset == "TH_vs_KH":
        t1, t2 = "TH", "KH"
    elif match_preset == "TH_vs_KP":
        t1, t2 = "TH", "KP"
    elif match_preset == "KP_vs_KH":
        t1, t2 = "KP", "KH"
    elif match_preset == "DOUBLE_5_SET":
        t1, t2 = "KH & JA", "TH & KP"
        match_type = "double"
        target_sets = 5
    elif match_preset == "SINGLE_2P_5_SET":
        t1, t2 = single_custom_t1, single_custom_t2
        target_sets = 5
    else:  # Custom / Guest
        t1 = guest_t1.strip()
        t2 = guest_t2.strip()

    scores = [(s1_1, s1_2), (s2_1, s2_2), (s3_1, s3_2)]
    if target_sets == 5:
        scores.extend([(s4_1 or 0, s4_2 or 0), (s5_1 or 0, s5_2 or 0)])

    db.add_match(match_date, match_type, t1, t2, target_sets, scores)
    return RedirectResponse(url="/?tab=history", status_code=303)

@app.post("/matches/{match_id}/edit")
def update_match_endpoint(
    match_id: int,
    match_date: str = Form(...),
    s1_1: int = Form(...), s1_2: int = Form(...),
    s2_1: int = Form(...), s2_2: int = Form(...),
    s3_1: int = Form(...), s3_2: int = Form(...),
    s4_1: int = Form(None), s4_2: int = Form(None),
    s5_1: int = Form(None), s5_2: int = Form(None),
):
    m = db.get_match_by_id(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="Kamp ikke fundet")
    scores = [(s1_1, s1_2), (s2_1, s2_2), (s3_1, s3_2)]
    if m["target_sets"] == 5:
        scores.extend([(s4_1 or 0, s4_2 or 0), (s5_1 or 0, s5_2 or 0)])

    db.update_match(match_id, match_date, scores)
    return RedirectResponse(url="/?tab=history", status_code=303)

@app.post("/matches/{match_id}/delete")
def delete_match_endpoint(match_id: int):
    db.delete_match(match_id)
    return RedirectResponse(url="/?tab=history", status_code=303)

@app.get("/backup/download")
def download_backup():
    csv_data = db.export_csv()
    return PlainTextResponse(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=badminton_backup.csv"}
    )

@app.post("/backup/restore")
async def restore_backup(file: UploadFile = File(...)):
    content = await file.read()
    db.import_csv(content.decode("utf-8"))
    return RedirectResponse(url="/?tab=history", status_code=303)
