import collections
import json
import os

from cosalib.s3 import (
    head_object,
    list_objects,
    download_file,
    delete_object
)

from cosalib.aws import (
    deregister_ami,
    delete_snapshot
)

Build = collections.namedtuple('Build', ['id', 'timestamp', 'images', 'arches'])


def get_unreferenced_s3_builds(active_build_set, bucket, prefix):
    """
    Scans s3 bucket and returns a list of build ID in the prefix

    :param active_build_set: list of known builds
    :type active_build_set: list
    """
    s3_prefixes = list_objects(bucket, prefix, result_key='CommonPrefixes')
    s3_matched = set()
    s3_unmatched = set()
    for prefix in s3_prefixes:
        prefix = prefix['Prefix']
        buildid = prefix.replace(prefix, '').rstrip("/")
        if buildid not in active_build_set:
            s3_unmatched.add(buildid)
        else:
            s3_matched.add(buildid)
    for buildid in active_build_set:
        if buildid not in s3_matched:
            print(f"WARNING: Failed to find build in S3: {buildid}")
    return s3_unmatched


def fetch_build_meta(builds, buildid, arch, bucket, prefix):
    build_dir = builds.get_build_dir(buildid, arch)

    # Fetch missing meta.json paths
    meta_json_path = os.path.join(build_dir, "meta.json")
    if not os.path.exists(meta_json_path):
        # Fetch it from s3
        os.makedirs(build_dir, exist_ok=True)
        s3_key = f"{prefix}{buildid}/{arch}/meta.json"
        head_result = head_object(bucket, s3_key)
        print(f"{s3_key}: {head_result}")
        if head_result:
            download_file(bucket, s3_key, meta_json_path)
        else:
            print(f"Failed to find object at {s3_key}")
            return None

    buildmeta_path = os.path.join(meta_json_path)
    with open(buildmeta_path) as f:
        buildmeta = json.load(f)
        images = {
            'amis': buildmeta.get('amis') or [],
            'azure': buildmeta.get('azure') or [],
            'gcp': buildmeta.get('gcp') or [],
        }
        return Build(
            id=buildid,
            timestamp=buildmeta['coreos-assembler.build-timestamp'],
            images=images,
            arches=arch
        )


def delete_build(build, bucket, prefix):
    # Unregister AMIs and snapshots
    for ami in build.images['amis']:
        region_name = ami.get('name')
        ami_id = ami.get('hvm')
        snapshot_id = ami.get('snapshot')
        if ami_id and region_name:
            deregister_ami(ami_id, region=region_name)
        if snapshot_id and region_name:
            delete_snapshot(snapshot_id, region=region_name)

    # Delete s3 bucket
    print(f"Deleting key {prefix}{build.id} from bucket {bucket}")
    delete_object(bucket, f"{prefix}{str(build.id)}")