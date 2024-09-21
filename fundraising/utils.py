def user_address_choices(user):
    addresses = [("", "---------")]
    if user is None:
        return addresses
    for address in user.addresses.all():
        address_choice = address.parse_address()
        addresses.append((address.id, address_choice))
    return addresses
