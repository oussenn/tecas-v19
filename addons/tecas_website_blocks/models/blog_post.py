import json
import re

from odoo import api, models

from .tecas_autosync import _schedule

# The value inside cover_properties is a css declaration: url("/web/image/...").
_COVER_URL = re.compile(r'url\(\s*[\'"\\]*(?P<url>[^\'")\\]+)', re.I)
_FIRST_IMG = re.compile(r'<img[^>]+src="(?P<url>[^"]+)"', re.I)


class BlogPost(models.Model):
    _inherit = 'blog.post'

    # What the news block shows: the headline, whether the post is online at
    # all, and the picture. cover_properties holds the picture as a css
    # declaration, hence the parsing below.
    _TECAS_WATCHED = {'name', 'is_published', 'website_published', 'active',
                      'cover_properties', 'content', 'post_date'}

    def _tecas_cover_url(self):
        """The post's picture, or False when it has none.

        Odoo stores a blog cover as a css `background-image` inside the
        cover_properties json, so there is no image field to point an <img> at.
        A post without a cover falls back to the first picture in its body —
        which is what a reader would have seen as the article's image anyway —
        and the block draws its own placeholder when there is neither.

        The json is decoded rather than pattern-matched: read raw, the field
        reads `url(\\"/web/image/...\\")`, and a regex run over the escaped text
        captures the backslash instead of the path — which is how the homepage
        briefly showed cards with src="/\\".
        """
        self.ensure_one()
        raw = self.cover_properties or ''
        try:
            declaration = json.loads(raw).get('background-image') or ''
        except ValueError:
            declaration = raw
        match = _COVER_URL.search(declaration)
        if match and match.group('url') not in ('none', 'None'):
            return match.group('url')
        match = _FIRST_IMG.search(self.content or '')
        return match.group('url') if match else False

    @api.model
    def _tecas_latest_posts(self, limit=3):
        """The posts the news block lists: newest first, published only."""
        return self.sudo().search(
            [('is_published', '=', True)], order='post_date desc, id desc', limit=limit)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(self._TECAS_WATCHED.intersection(vals) for vals in vals_list):
            _schedule(self.env)
        return records

    def write(self, vals):
        result = super().write(vals)
        if self._TECAS_WATCHED.intersection(vals):
            _schedule(self.env)
        return result

    def unlink(self):
        result = super().unlink()
        _schedule(self.env)
        return result
