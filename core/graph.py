"""Thin Microsoft Graph client. All functions take the Django user and use
their delegated token (silently refreshed via accounts.microsoft)."""

from urllib.parse import quote

import requests

from accounts.microsoft import get_graph_token

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphError(Exception):
    def __init__(self, status_code, message):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Graph {status_code}: {message}")


def _get(user, path, params=None, headers=None, stream=False):
    token = get_graph_token(user)
    all_headers = {"Authorization": f"Bearer {token}"}
    if headers:
        all_headers.update(headers)
    resp = requests.get(
        f"{GRAPH_BASE}{path}", params=params, headers=all_headers, stream=stream, timeout=30
    )
    if resp.status_code >= 400:
        try:
            message = resp.json()["error"]["message"]
        except Exception:
            message = resp.text[:200]
        raise GraphError(resp.status_code, message)
    return resp


def list_sites(user):
    """SharePoint sites the user can see, gathered from several endpoints.

    The search-based listing ("/sites?search=*") 500s on freshly created
    tenants until Microsoft's search index is provisioned, so it is only a
    bonus source; followed sites and the root site are the reliable ones.
    """
    select = {"$select": "id,displayName,webUrl"}
    sites = {}

    for path, params in [
        ("/me/followedSites", select),
        ("/sites/root", select),
        ("/sites", {"search": "*", **select}),
    ]:
        try:
            data = _get(user, path, params=params).json()
        except GraphError:
            continue
        for site in data.get("value", [data] if "id" in data else []):
            sites[site["id"]] = site

    return sorted(sites.values(), key=lambda s: (s.get("displayName") or "").lower())


def list_drives(user, site_id):
    """Document libraries of a site."""
    params = {"$select": "id,name,driveType,webUrl"}
    return _get(user, f"/sites/{site_id}/drives", params=params).json()["value"]


def list_children(user, drive_id, item_id="root"):
    """Folder contents. item_id='root' means the drive's root folder."""
    path = f"/drives/{drive_id}/root/children" if item_id == "root" else f"/drives/{drive_id}/items/{item_id}/children"
    params = {"$select": "id,name,folder,file,size,lastModifiedDateTime", "$top": "200"}
    return _get(user, path, params=params).json()["value"]


def get_item(user, drive_id, item_id="root"):
    path = f"/drives/{drive_id}/root" if item_id == "root" else f"/drives/{drive_id}/items/{item_id}"
    params = {"$select": "id,name,eTag,file,size,parentReference"}
    return _get(user, path, params=params).json()


def upload_file(user, drive_id, parent_id, name, data):
    """Upload (or replace) a file in a folder via an upload session, which
    works for any file size. Returns the resulting driveItem."""
    token = get_graph_token(user)
    auth = {"Authorization": f"Bearer {token}"}

    session_url = f"{GRAPH_BASE}/drives/{drive_id}/items/{parent_id}:/{quote(name)}:/createUploadSession"
    body = {"item": {"@microsoft.graph.conflictBehavior": "replace", "name": name}}
    resp = requests.post(session_url, headers=auth, json=body, timeout=30)
    if resp.status_code >= 400:
        raise GraphError(resp.status_code, resp.text[:200])
    upload_url = resp.json()["uploadUrl"]  # pre-authenticated, no auth header needed

    total = len(data)
    chunk_size = 3_276_800  # must be a multiple of 320 KiB
    result = None
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total) - 1
        headers = {"Content-Range": f"bytes {start}-{end}/{total}"}
        result = requests.put(upload_url, data=data[start : end + 1], headers=headers, timeout=120)
        if result.status_code >= 400:
            raise GraphError(result.status_code, result.text[:200])
    return result.json()


def stream_content(user, drive_id, item_id, range_header=None):
    """Streaming response for a file's bytes. Graph 302-redirects to a
    pre-authenticated download URL; requests follows it and drops the
    Authorization header on the host change, which is what we want."""
    headers = {"Range": range_header} if range_header else None
    return _get(user, f"/drives/{drive_id}/items/{item_id}/content", headers=headers, stream=True)
