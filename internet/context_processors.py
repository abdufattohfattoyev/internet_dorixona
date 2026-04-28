from .models import Cart, CartItem, Category

def cart(request):
    cart_count = 0
    session_key = request.session.session_key
    if session_key:
        cart, created = Cart.objects.get_or_create(session_key=session_key)
        cart_count = cart.cartitem_set.count()
    categories = Category.objects.all()
    return {'cart_count': cart_count, 'categories': categories}