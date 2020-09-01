# Copyright 2020 - Jonas Hauquier

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to
# deal in the Software without restriction, including without limitation the
# rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
# sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
# FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

""" This plugin generates additional images intended for high DPI screens.
High DPI images are used by themes that support it, such as the Lychee theme.

If the ``create_high_dpi`` setting is set to True, this plugin will generate
images at double the configured size for each of the images.
It will attach the properties ``url_2x`` and ``thumbnail_2x`` to media elements.
"""

import logging
import os
from os.path import isfile, join, splitext

from sigal import signals
from sigal.gallery import Media
from sigal.utils import cached_property, url_from_path
import sigal.image
import sigal.video

logger = logging.getLogger(__name__)

def get_hidpi_filename(filename):
    fn, ext = os.path.splitext(filename)
    return fn + "_2x" + ext
    
def generate_hidpi_image(filepath, outname, settings):
    force = False  # TODO do not have access to cmdline arg "force"
    if os.path.isfile(outname) and not force:
        logger.info("HighDPI %s exists - skipping", outname)
        return outname

    options = sigal.image.get_processing_options(outname, settings)
    width, height = settings['img_size']
    hidpi_settings = settings.copy()
    hidpi_settings['img_size'] = (2*width, 2*height)

    try:
        sigal.image.generate_image(filepath, outname, hidpi_settings, options=options)
    except Exception as e:
        logger.error('Failed to generate high DPI image: %r', e)
        if logger.getEffectiveLevel() == logging.DEBUG:
            #logger.debug("Exception:", exc_info=True, stack_info=True)
            import traceback
            traceback.print_exc()

    return outname


def get_hidpi_image(media):
    settings = media.settings
    filepath = media.src_path

    logger.info('Processing high DPI image %s', filepath)
    filename = os.path.split(filepath)[1]
    filename_2x = get_hidpi_filename(filename)
    outpath = os.path.join(settings['destination'], media.path)
    outname = os.path.join(outpath, filename_2x)
    
    return generate_hidpi_image(filepath, outname, settings)

def get_hidpi_video(media):
    # TODO
    return ""

def get_url_hidpi(media):
    if media.type == 'image':
        return url_from_path(get_hidpi_image(media))
    elif media.type == 'video':
        return url_from_path(get_hidpi_video(media))

def get_thumbnail_hidpi(media):
    thumb_2x_name = get_hidpi_filename(media.thumb_name)
    thumb_2x_path = join(media.settings['destination'], media.path, thumb_2x_name)

    if not os.path.isfile(thumb_2x_path):
        logger.debug('Generating high DPI thumbnail for %r', media)
        path = (media.dst_path if os.path.exists(media.dst_path)
                else media.src_path)

        try:
            # if thumbnail is missing (if settings['make_thumbs'] is False)
            s = media.settings
            w, h = s['thumb_size']
            hidpi_size = (2*w, 2*h)
            if media.type == 'image':
                sigal.image.generate_thumbnail(
                    path, thumb_2x_path, hidpi_size,
                    fit=s['thumb_fit'])
            elif media.type == 'video':
                sigal.video.generate_thumbnail(
                    path, thumb_2x_path, hidpi_size,
                    s['thumb_video_delay'], fit=s['thumb_fit'],
                    converter=s['video_converter'])
        except Exception as e:
            logger.error('Failed to generate high DPI thumbnail: %s', e)
            if logger.getEffectiveLevel() == logging.DEBUG:
                #logger.debug("Exception:", exc_info=True, stack_info=True)
                import traceback
                traceback.print_exc()
            return
    return url_from_path(thumb_2x_name)
    
def generate_hidpi(img, settings=None):
    # TODO
    generate_hidpi_image(filepath, outname, settings)
    generate_hidpi_thumbnail(filepath, outname, settings)


def init_hidpi():
    Media.url_2x = cached_property(get_url_hidpi)
    Media.thumbnail_2x = cached_property(get_thumbnail_hidpi)
    # TODO make sure resizing happens in parallel, for this to work, the img_resized signal will have to pass some extra parameters, otherwise only available in the Media object which is created at a later time
    #signals.img_resized.connect(generate_hidpi)  # Using this callback, we can generate images in parallel jobs

def register(settings):
    if settings.get('create_high_dpi'):
        logger.info('High DPI plugin enabled')
        init_hidpi()
