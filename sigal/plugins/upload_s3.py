"""Plugin to upload generated files to Amazon S3.

This plugin requires boto_. All generated files are uploaded to a specified S3
bucket.  When using this plugin you have to make sure that the bucket already
exists and the you have access to the S3 bucket. The access credentials are
managed by boto_ and can be given as environment variables, configuration files
etc. More information can be found on the boto_ documentation.

.. _boto3: https://pypi.org/project/boto3/

Settings (all settings are wrapped in ``upload_s3_options`` dict):

- ``bucket``: The to-be-used bucket for uploading.
- ``policy``: Specifying access control to the uploaded files. Possible values:
  private, public-read, public-read-write, authenticated-read
- ``overwrite``: Boolean indicating if all files should be uploaded and
  overwritten or if already uploaded files should be skipped.
- ``max_age``: Optional, Integer indicating the number of seconds that the
  cache control should be set by default
- ``media_max_age``: Optional, Integer indicates the number of seconds that
  cache control hould be set for media files
- ``credentials_profile``: Optional, String that refers to profile to use in
  ~/.aws/credentials (defaults to "default")
- ``enable_inline``: Optional, Boolean that when set to True will set the
  ContentDisposition and mime type in Content-Type metadata fields of image files,
  so that they can be inlined on a webpage.
- ``md5_hash``: Optional, Boolean that when set to True uses MD5 hashes to 
  determine whether a file has to be re-uploaded (defaults to False)
  ~/.aws/credentials (defaults to "False")


"""

import logging
import os
import mimetypes
import tempfile

from click import progressbar

from sigal import signals

logger = logging.getLogger(__name__)

def get_s3_key(gallery, f):
    subfolder = gallery.settings['upload_s3_options'].get('bucket_subfolder', '')
    if subfolder:
        return os.path.join(subfolder, f)
    return f

def handle_file(gallery, f, key, size, s3, bucket_name, bucket):
    import botocore.exceptions
    if gallery.settings['upload_s3_options']['overwrite'] is False:
        # Check if file was uploaded before
        try:
            key_obj = s3.meta.client.head_object(Bucket=bucket_name, Key=key)
            upload_file_if_changed(gallery, f, size, key_obj, bucket, s3)
        except botocore.exceptions.ClientError:
            # TODO can also be because of access denied error, but mostly you want to silence this error
            import traceback
            traceback.print_exc()
            # File does not exist
            upload_file(gallery, bucket, f, key)

    else:
        # Force overwrite file
        upload_file(gallery, bucket, f)

def upload_s3(gallery, settings=None):
    import boto3
    upload_files = []

    # Get local files
    for root, dirs, files in os.walk(gallery.settings['destination']):
        for f in files:
            path = os.path.join(
                root[len(gallery.settings['destination']) + 1:], f)
            size = os.path.getsize(os.path.join(root, f))
            upload_files += [(path, size)]

    # Connect to specified bucket
    session = boto3.Session(profile_name=gallery.settings['upload_s3_options'].get("credentials_profile", "default"))
    s3 = session.resource('s3')
    bucket_name = gallery.settings['upload_s3_options']['bucket']
    bucket = s3.Bucket(bucket_name)

    # Create robots.txt to fend off search engine crawlers
    if gallery.settings['upload_s3_options'].get('create_robots_txt', False):
        logger.debug("Creating robots.txt")
        with tempfile.TemporaryDirectory() as tmp_dir_path:
            robots_txt_file = os.path.join(tmp_dir_path, 'robots.txt')
            with open(robots_txt_file, 'w') as f:
                f.write("""User-agent: *
Disallow: / """)
            # robots.txt lives only at the root of the domain (bucket)
            key = "robots.txt"
            size = os.path.getsize(robots_txt_file)
            handle_file(gallery, robots_txt_file, key, size, s3, bucket_name, bucket)

    # Upload the files
    with progressbar(upload_files, label="Uploading files to S3") as bar:
        for (f, size) in bar:
            key = get_s3_key(gallery, f)
            handle_file(gallery, f, key, size, s3, bucket_name, bucket)

def upload_file_if_changed(gallery, f, size, key, bucket, s3):
    metadata = {}
    try:
        metadata = key["Metadata"]
    except:
        pass
        
    def _update_cache_policy(gallery, f, key, s3):
        #logger.debug('Updating cache policy of %s if it differs', f)

        if key is None:
            return

        cache_metadata = generate_cache_metadata(gallery, f)
        cc = key.get('CacheControl', "")
        if cc != cache_metadata:
            logger.debug('Cache policy differs, updating metadata of %s', key)

            m = key["Metadata"]
            m["Cache-Control"] = cache_metadata
            extra_kwargs = {}
            if gallery.settings['upload_s3_options'].get('enable_inline', False):
                extra_kwargs["ContentDisposition"] = 'inline'
            s3.meta.client.copy_object(Bucket=bucket.name, Key=key,
                                       CopySource=os.path.join(bucket.name, key),
                                       CacheControl=cache_metadata,
                                       ContentType=get_mime_type(f),
                                       Metadata=m,
                                       MetadataDirective='REPLACE',
                                       **extra_kwargs)

    if gallery.settings['upload_s3_options'].get('md5_hash', False):
        # Compare MD5 hashes for checking difference
        s3_md5 = metadata.get('md5chksum', None)
        f_path = os.path.join(gallery.settings['destination'], f)
        with open(f_path, 'rb') as f_obj:
            local_md5 = get_md5_content_str(f_obj)
        if s3_md5 != local_md5:
            logger.debug("MD5 hash of file %s differs on S3, reuploading" % (f))
            upload_file(gallery, bucket, f, local_md5)
            return True
        else:
            logger.debug("Hash of file %s matches, skipping" % (f))
            _update_cache_policy(gallery, f, key, s3)
            return False
    else:
        # Use filesize for checking difference
        s3_size = key.get('ContentLength', None)
        if s3_size != size:
            logger.debug("File sizes differ, reuploading %s" % (f))
            upload_file(gallery, bucket, f)
            return True
        else:
            logger.debug("Skipping file %s" % (f))
            _update_cache_policy(gallery, f, key, s3)
            return False

def generate_cache_metadata(gallery, f):
    filename, file_extension = os.path.splitext(f)

    proposed_cache_control = ""
    if 'media_max_age' in gallery.settings['upload_s3_options'] and \
            file_extension in ['.jpg', '.png', '.webm', '.mp4']:
        proposed_cache_control = "max-age=%s" % \
            gallery.settings['upload_s3_options']['media_max_age']
    elif 'max_age' in gallery.settings['upload_s3_options']:
        proposed_cache_control = "max-age=%s" % \
            gallery.settings['upload_s3_options']['max_age']
    return proposed_cache_control

def get_md5_content_str(f_obj):
    import hashlib
    import base64
    digest = hashlib.md5(f_obj.read()).digest()
    content_md5_str = base64.b64encode(digest)
    f_obj.seek(0)
    return content_md5_str.decode('ascii')
    
def get_mime_type(file_path):
    return mimetypes.guess_type(file_path)[0]

def upload_file(gallery, bucket, f, key, file_md5_hash=None):
    logger.debug("Uploading file %s" % (f))
    
    cache_metadata = generate_cache_metadata(gallery, f)

    # ACL must be one of 'private'|'public-read'|'public-read-write'|'authenticated-read'|'aws-exec-read'|'bucket-owner-read'|'bucket-owner-full-control'
    acl_policy = gallery.settings['upload_s3_options']['policy']
    f_path = os.path.join(gallery.settings['destination'], f)

    extra_kwargs = dict()
    if cache_metadata:
        extra_kwargs["CacheControl"] = cache_metadata
    if gallery.settings['upload_s3_options'].get('enable_inline', False):
        extra_kwargs["ContentDisposition"] = 'inline'

    with open(f_path, 'rb') as f_obj:
        if gallery.settings['upload_s3_options'].get('md5_hash', False):
            if file_md5_hash is None:
                file_md5_hash = get_md5_content_str(f_obj)
            extra_kwargs["ContentMD5"] = file_md5_hash
            extra_kwargs["Metadata"] = { "md5chksum": file_md5_hash }

        bucket.put_object(Body=f_obj,
                      Key=key,
                      ACL=acl_policy,
                      ContentType=get_mime_type(f),
                      **extra_kwargs)

    #s3.get_bucket_website(Bucket='BUCKET_NAME')


def register(settings):
    if settings.get('upload_s3_options'):
        signals.gallery_build.connect(upload_s3)
