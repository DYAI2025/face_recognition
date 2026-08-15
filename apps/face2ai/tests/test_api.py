def image_headers():
    return {"content-type": "image/jpeg"}


def test_health_and_status(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    response = client.get("/api/status")
    assert response.status_code == 200
    assert response.json()["engine_available"] is True


def test_unknown_enroll_known(client, fake_engine, face):
    fake_engine.faces = [face]
    unknown = client.post("/api/recognize", content=b"frame", headers=image_headers())
    assert unknown.status_code == 200
    assert unknown.json()["state"] == "UNKNOWN"
    assert unknown.json()["can_enroll"] is True

    enrolled = client.post("/api/enroll?display_name=PersonA&consent=true", content=b"frame", headers=image_headers())
    assert enrolled.status_code == 201
    assert enrolled.json()["display_name"] == "PersonA"

    known = client.post("/api/recognize", content=b"frame", headers=image_headers())
    assert known.status_code == 200
    assert known.json()["state"] == "KNOWN"
    assert known.json()["faces"][0]["display_name"] == "PersonA"


def test_multiple_faces_block_enrollment(client, fake_engine, face):
    fake_engine.faces = [face, face]
    response = client.post("/api/recognize", content=b"frame", headers=image_headers())
    assert response.json()["state"] == "MULTIPLE_FACES"


def test_content_type_is_enforced(client):
    response = client.post("/api/recognize", content=b"frame", headers={"content-type": "application/json"})
    assert response.status_code == 415
