from wagtail.images.formats import Format, register_image_format

register_image_format(Format('fifty_pct', '50%', 'richtext-image half-page', 'scale-50'))
register_image_format(Format('twentyfive_pct', '25%', 'richtext-image quarter-page', 'scale-50'))
