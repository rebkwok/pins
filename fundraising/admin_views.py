from django.shortcuts import render, get_object_or_404

from wagtail.admin.ui.tables import Table, TitleColumn, Column

from .models import Auction, AuctionItem

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
            TitleColumn("__str__", label="Item", url_name="auction_item_log"),
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


def auction_item_log(request, pk):
    auction_item = get_object_or_404(AuctionItem, pk=pk)
    object_list = auction_item.logs.all()
    table = Table(
        [
            Column("timestamp"),
            Column("log",),
        ],
        object_list,
    )
    
    return render(request, 'fundraising/admin/auction_item_log.html', {
        "object_list": object_list,
        "table": table,
        "title": f"Log of bids for {auction_item.title}"
    })


def auction_docs(request):
    return render(request, 'fundraising/admin/auction_docs.html')
