from django.shortcuts import render, get_object_or_404

from wagtail.admin.ui.tables import Table, TitleColumn, Column

from .models import Auction

def auctions_index(request):
    auctions = Auction.objects.all()
    table = Table(
        [
            TitleColumn("__str__", label="Name", url_name="auction_detail",),
            Column("open_at"),
            Column("close_at"),    
        ],
        auctions,
    )

    return render(request, 'fundraising/admin/auctions_index.html', {
        "object_list": auctions, "table": table, "page_title": "Auctions",
    })


def auction_detail(request, pk):
    auction = get_object_or_404(Auction, pk=pk)
    object_list = auction.get_children().specific()
    table = Table(
        [
            Column("__str__", label="Item"),
            Column("starting_bid",),
            Column("postage",),
            Column("donor",),
            Column("donor_email",),
            Column("bid_count", label="# bids"),
            Column("current_winning_bid",),
            Column("winner_name"),
            Column("total_due"),
        ],
        object_list,
    )
    
    return render(request, 'fundraising/admin/auction_detail.html', {
        'auction': auction,
        "object_list": object_list,
        "table": table,
    })