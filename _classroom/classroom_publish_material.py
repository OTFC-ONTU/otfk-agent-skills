"""Publish one plan material; default is dry-run.

Replacing an empty draft requires --replace-empty-draft with its exact ID
and prior human authorization. Published posts are never replaced.
"""
import argparse
import json
from pathlib import Path

from classroom_auth import get_service
from classroom_sync import build_materials
from drive_files import DriveUploader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan')
    parser.add_argument('title')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--replace-empty-draft', metavar='ID')
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding='utf-8'))
    item = next(i for t in plan['topics'] for i in t['items'] if i['title'] == args.title)
    assert item['type'] == 'material' and item['state'] == 'PUBLISHED'
    assert item.get('materials'), 'No attachments in plan'
    svc = get_service()
    cid = str(plan['course']['id'])
    course = svc.courses().get(id=cid).execute()
    api = svc.courses().courseWorkMaterials()
    matches = []
    page = None
    while True:
        response = api.list(courseId=cid, pageToken=page,
                            courseWorkMaterialStates=['PUBLISHED', 'DRAFT']).execute()
        matches.extend(x for x in response.get('courseWorkMaterial', [])
                       if x['title'] == args.title)
        page = response.get('nextPageToken')
        if not page:
            break
    assert len(matches) == 1, 'Expected exactly one existing material'
    post = matches[0]
    uploader = DriveUploader(course, args.plan)
    if post['state'] == 'PUBLISHED':
        expected = build_materials(item, uploader, apply=False)
        actual_ids = [m['driveFile']['driveFile']['id'] for m in post.get('materials', [])]
        expected_ids = [m['driveFile']['driveFile']['id'] for m in expected]
        assert actual_ids == expected_ids, 'Published attachments differ from plan'
        print('Без змін:', post['title'], post['state'], post.get('alternateLink', ''))
        return
    assert post['state'] == 'DRAFT'
    assert args.replace_empty_draft == post['id'], 'Explicit draft ID required'
    assert not post.get('materials'), 'Draft already has attachments'
    if not args.apply:
        build_materials(item, uploader, apply=False)
        print('DRY-RUN: replace empty draft with published material:', post['id'], post['title'])
        return
    materials = build_materials(item, uploader, apply=True)
    assert len(materials) == len(item['materials'])
    fresh = api.get(courseId=cid, id=post['id']).execute()
    assert fresh['state'] == 'DRAFT' and not fresh.get('materials')
    assert fresh['title'] == item['title']
    body = {'title': item['title'], 'description': item['description'],
            'state': 'PUBLISHED', 'topicId': fresh['topicId'], 'materials': materials}
    api.delete(courseId=cid, id=fresh['id']).execute()
    created = api.create(courseId=cid, body=body).execute()
    result = api.get(courseId=cid, id=created['id']).execute()
    assert result['state'] == 'PUBLISHED'
    assert len(result.get('materials', [])) == len(materials)
    print(json.dumps({'title': result['title'], 'state': result['state'],
                      'attachments': result['materials'],
                      'url': result.get('alternateLink')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
