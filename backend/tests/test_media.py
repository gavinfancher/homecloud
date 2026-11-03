import io

import pycdlib
import yaml

from app import media


def read_iso(data: bytes) -> dict[str, str]:
    iso = pycdlib.PyCdlib()
    iso.open_fp(io.BytesIO(data))
    files = {}
    for name in ("user-data", "meta-data", "autounattend.xml"):
        out = io.BytesIO()
        try:
            iso.get_file_from_iso_fp(out, joliet_path=f"/{name}")
        except pycdlib.pycdlibexception.PyCdlibInvalidInput:
            continue
        files[name] = out.getvalue().decode()
    return files


def test_ubuntu_seed():
    files = read_iso(media.ubuntu_seed("web1"))
    assert files["user-data"].startswith("#cloud-config\n")
    user_data = yaml.safe_load(files["user-data"])
    assert user_data["hostname"] == "web1"
    assert user_data["users"][0]["ssh_authorized_keys"] == ["ssh-ed25519 AAAAtest test@laptop"]
    assert "qemu-guest-agent" in user_data["packages"]
    assert yaml.safe_load(files["meta-data"])["local-hostname"] == "web1"


def test_windows_answer_is_valid_xml_with_escaped_password():
    import xml.etree.ElementTree as ET

    xml = read_iso(media.windows_answer("ad-client"))["autounattend.xml"]
    root = ET.fromstring(xml)
    ns = {"u": "urn:schemas-microsoft-com:unattend"}
    assert root.find(".//u:ComputerName", ns).text == "AD-CLIENT"
    values = [v.text for v in root.findall(".//u:AdministratorPassword/u:Value", ns)]
    assert values == ["Pa<ss>&word1!"]  # escaped in the file, intact once parsed
