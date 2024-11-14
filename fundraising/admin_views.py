from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils.safestring import mark_safe

from wagtail.admin.ui.tables import (
    BooleanColumn, Table, TitleColumn, Column, StatusFlagColumn, UserColumn, ReferencesColumn
)
from wagtail.admin.ui.tables.pages import PageStatusColumn

from .models import Auction, AuctionItem, Bid

def auctions_index(request):
    auctions = Auction.objects.all()
    table = Table(
        [
            TitleColumn("__str__", label="Name", url_name="auction_detail",),
            PageStatusColumn("status"),
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

    def _get_winning_bid(bid):
        if bid.active_bids:
            return f"£{bid.current_winning_bid()}"
        return "-"
    
    def _get_total_due(auction_item):
        if auction_item.total_due():
            return f"£{auction_item.total_due()}"
        return "-"
    
    sort_by = request.GET.get("ordering")
    match sort_by:
        case "winner_notified":
            object_list = sorted(object_list, key=lambda x: x.winner_notified())
        case "-winner_notified":
            object_list = sorted(object_list, key=lambda x: x.winner_notified(), reverse=True)
        case "donor_notified":
            object_list = sorted(object_list, key=lambda x: x.donor_notified())
        case "-donor_notified":
            object_list = sorted(object_list, key=lambda x: x.donor_notified(), reverse=True)
        case "donor":
            object_list = sorted(object_list, key=lambda x: x.donor)
        case "-donor":
            object_list = sorted(object_list, key=lambda x: x.donor, reverse=True)
        case "winner":
            object_list = sorted(object_list, key=lambda x: x.winner() or "")
        case "-winner":
            object_list = sorted(object_list, key=lambda x: x.winner() or "", reverse=True)
        case "total_due":
            object_list = sorted(object_list, key=_get_total_due)
        case "-total_due":
            object_list = sorted(object_list, key=_get_total_due, reverse=True)
        case "winning_bid":
            object_list = sorted(object_list, key=_get_winning_bid)
        case "-winning_bid":
            object_list = sorted(object_list, key=_get_winning_bid, reverse=True)

    table = Table(
        [
            TitleColumn("title", label="Item (click name for details)", url_name="auction_item_result"),
            Column("category"),
            PageStatusColumn("status"),
            Column("donor", sort_key="donor"),
            Column("bid_count", label="# bids"),
            Column("current_winning_bid", sort_key="winning_bid", label="Winning bid", accessor=lambda x: _get_winning_bid(x)),
            Column("winner", sort_key="winner"),
            BooleanColumn("winner_notified", sort_key="winner_notified"),
            BooleanColumn("donor_notified", sort_key="donor_notified"),
            Column("total_due", sort_key="total_due", accessor=lambda x: _get_total_due(x)),
        ],
        object_list,
        base_url=reverse("auction_detail", args=(pk,)),
        ordering=sort_by
    )
    
    return render(request, 'fundraising/admin/auction_detail.html', {
        'auction': auction,
        "parent": auction,
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
        "auction_item": auction_item,
        "table": table,
        "title": f"Log of bids for {auction_item.title}"
    })


def auction_item_bids(request, pk):
    auction_item = get_object_or_404(AuctionItem, pk=pk)
    object_list = auction_item.bids.all()
    table = Table(
        [
            Column("link", label="", accessor=lambda x: mark_safe(f"<a href='{x.admin_url()}'><svg class='icon icon-auction icon-link'><use href='#icon-link'></use></svg></a>")),
            UserColumn("user"),
            Column("amount",),
            StatusFlagColumn("withdrawn", label="Status", true_label="Withdrawn", false_label="Active"),
            BooleanColumn("is_winner", label="Winning bid?"),
        ],
        object_list,
    )
    
    return render(request, 'fundraising/admin/auction_item_bids.html', {
        "object_list": object_list,
        "auction_item": auction_item,
        "table": table,
        "title": f"All bids for {auction_item.title}"
    })


def auction_item_result(request, pk):
    auction_item = get_object_or_404(AuctionItem, pk=pk)
    winning_bid = auction_item.current_winning_bid_obj
    return render(request, 'fundraising/admin/auction_item_result.html',
        {
            "page_title": f"{auction_item.title}",
            "auction_item": auction_item,
            "winning_bid": winning_bid,
            "auction": auction_item.get_parent().specific,
        }
    )


def auction_item_bid(request, pk):
    bid = get_object_or_404(Bid, pk=pk)
    auction_item = bid.auction_item
    return render(request, 'fundraising/admin/auction_item_bid.html',
        {
            "page_title": f"{auction_item.title}",
            "page_subtitle": f"Bid from {bid.user}",
            "header_icon": "leaf",
            "auction_item": auction_item,
            "bid": bid,
            "auction": auction_item.get_parent().specific,
            "winning_bid": not bid.withdrawn and (bid.amount == auction_item.current_winning_bid()),
        }
    )


def auction_docs(request):
    return render(request, 'fundraising/admin/auction_docs.html')
