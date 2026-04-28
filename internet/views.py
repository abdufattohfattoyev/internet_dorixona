import logging
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone
from .utils import send_telegram_message
from .forms import OrderForm
from .models import Category, Product, Cart, CartItem, Order, OrderItem

logger = logging.getLogger(__name__)


def get_cart(request):
    session_key = request.session.session_key
    if not session_key:
        request.session.create()
        session_key = request.session.session_key
    cart, created = Cart.objects.get_or_create(session_key=session_key)
    return cart


def filter_and_paginate_products(products, request, per_page=10):
    """Qidiruv va paginatsiya logikasini umumiy funksiyaga ajratish"""
    query = request.GET.get('q')
    if query:
        products = products.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )

    products = products.order_by('created_at')  # Eng eski mahsulotlar boshida, eng yangilar oxirida
    paginator = Paginator(products, per_page)
    page_number = request.GET.get('page')
    products_page = paginator.get_page(page_number)
    return products_page

def home(request):
    all_categories = Category.objects.all()
    products = Product.objects.select_related('category').all().order_by('created_at')  # Boshlang'ich saralash

    cart = get_cart(request)
    cart_products = [item.product for item in cart.cartitem_set.all()]

    # Kategoriya filtri
    category_slug = request.GET.get('category')
    if category_slug:
        current_category = get_object_or_404(Category, slug=category_slug)
        products = products.filter(category__slug=category_slug)
        current_index = list(all_categories).index(current_category)
        start_index = max(0, current_index - 2)
        end_index = min(len(all_categories), current_index + 3)
        visible_categories = all_categories[start_index:end_index]
    else:
        # Agar kategoriya tanlanmagan bo'lsa, birinchi 5 ta kategoriya
        visible_categories = all_categories[:5]

    products_page = filter_and_paginate_products(products, request)

    return render(request, 'index.html', {
        'categories': all_categories,
        'visible_categories': visible_categories,
        'products': products_page,
        'cart': cart,
        'cart_products': cart_products
    })


def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)
    cart = get_cart(request)
    product_in_cart = cart.cartitem_set.filter(product=product).exists()

    return render(request, 'product_detail.html', {
        'product': product,
        'cart': cart,
        'product_in_cart': product_in_cart
    })


def cart_detail(request):
    cart = get_cart(request)
    return render(request, 'cart.html', {'cart': cart})


def category_detail(request, slug):
    category = get_object_or_404(Category, slug=slug)
    products = Product.objects.filter(category=category)
    cart = get_cart(request)
    cart_products = [item.product for item in cart.cartitem_set.all()]

    all_categories = Category.objects.all()
    current_index = list(all_categories).index(category)
    start_index = max(0, current_index - 2)
    end_index = min(len(all_categories), current_index + 3)
    visible_categories = all_categories[start_index:end_index]

    products_page = filter_and_paginate_products(products, request)

    return render(request, 'category_detail.html', {
        'category': category,
        'categories': all_categories,
        'visible_categories': visible_categories,
        'products': products_page,
        'cart': cart,
        'cart_products': cart_products
    })


@require_POST
def add_to_cart(request, product_id):
    try:
        product = get_object_or_404(Product, id=product_id)
        cart = get_cart(request)

        cart_item_exists = CartItem.objects.filter(cart=cart, product=product).exists()

        if cart_item_exists:
            return JsonResponse({
                'success': False,
                'cart_count': cart.cartitem_set.count(),
                'already_in_cart': True,
                'message': 'Bu mahsulot allaqachon savatda!'
            }, status=400)

        cart_item = CartItem.objects.create(
            cart=cart,
            product=product,
            quantity=1
        )
        logger.info(f"Mahsulot #{product.id} savatga qo'shildi (session: {cart.session_key})")

        return JsonResponse({
            'success': True,
            'cart_count': cart.cartitem_set.count(),
            'already_in_cart': False,
            'message': "Savatga qo'shildi!"
        })
    except Exception as e:
        logger.error(f"Savatga qo'shishda xato: {e}")
        return JsonResponse({
            'success': False,
            'message': "Xato yuz berdi, qayta urinib ko'ring."
        }, status=500)


@require_POST
def update_cart(request, item_id):
    try:
        cart_item = get_object_or_404(CartItem, id=item_id, cart=get_cart(request))
        quantity = int(request.POST.get('quantity', 1))

        if quantity > 0:
            cart_item.quantity = quantity
            cart_item.save()
            logger.info(f"Savat elementi #{item_id} yangilandi: quantity={quantity}")
        else:
            cart_item.delete()
            logger.info(f"Savat elementi #{item_id} o'chirildi")

        return JsonResponse({
            'success': True,
            'item_total': cart_item.get_total_price() if quantity > 0 else 0,
            'cart_total': cart_item.cart.get_total_price(),
            'cart_count': cart_item.cart.cartitem_set.count()
        })
    except Exception as e:
        logger.error(f"Savatni yangilashda xato: {e}")
        return JsonResponse({
            'success': False,
            'message': "Xato yuz berdi, qayta urinib ko'ring."
        }, status=500)


@require_POST
def remove_from_cart(request, item_id):
    try:
        cart_item = get_object_or_404(CartItem, id=item_id, cart=get_cart(request))
        cart_item.delete()
        logger.info(f"Savat elementi #{item_id} o'chirildi")

        return JsonResponse({
            'success': True,
            'cart_total': cart_item.cart.get_total_price(),
            'cart_count': cart_item.cart.cartitem_set.count()
        })
    except Exception as e:
        logger.error(f"Savatdan o'chirishda xato: {e}")
        return JsonResponse({
            'success': False,
            'message': "Xato yuz berdi, qayta urinib ko'ring."
        }, status=500)

def create_order_items(order, cart_items):
    order_items = [
        OrderItem(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=item.product.price
        )
        for item in cart_items
    ]
    OrderItem.objects.bulk_create(order_items)
    logger.info(f"Buyurtma #{order.id} uchun {len(order_items)} ta element yaratildi")


def send_order_notification(order, cart_items):
    local_tz = timezone.get_current_timezone()
    local_time = order.created_at.astimezone(local_tz)
    items_list = "\n".join(
        [
            f"{i}. {item.product.name} — {item.quantity} dona\n   └─ {item.product.price:,.0f} x {item.quantity} = {item.get_total_price():,.0f} so'm"
            for i, item in enumerate(cart_items, start=1)
        ]
    )
    notes_text = order.notes or "Yo'q"
    message = (
        f"💊 <b>Yangi Buyurtma Keldi! #{order.id}</b> 💊\n\n"
        f"👤 <b>Mijoz:</b> {order.first_name}\n"
        f"📞 <b>Telefon:</b> {order.phone}\n"
        f"📍 <b>Manzil:</b> {order.region}, {order.city} — {order.address}\n"
        f"💬 <b>Izoh:</b> {notes_text}\n\n"
        f"🏥 <b>Dorilar:</b>\n{items_list}\n\n"
        f"💰 <b>Jami summa:</b> {order.total_price:,.0f} so'm\n"
    )
    try:
        send_telegram_message(message)
        logger.info(f"Buyurtma #{order.id} uchun Telegram xabari yuborildi")
    except Exception as e:
        logger.error(f"Telegram xabarini yuborishda xato (buyurtma #{order.id}): {e}")


def checkout(request):
    cart = get_cart(request)
    all_categories = Category.objects.all()
    visible_categories = all_categories[:5]

    if not cart.cartitem_set.exists():
        messages.error(request, "Savat bo'sh! Iltimos, mahsulot qo'shing.")
        logger.warning(f"Bo'sh savat bilan checkoutga kirish (session: {cart.session_key})")
        return redirect('cart')

    if request.method == 'POST':
        delivery_method = request.POST.get('delivery_method', 'manual')

        if delivery_method == 'map':
            name  = request.POST.get('first_name', '').strip()
            phone = request.POST.get('phone', '').strip()
            notes = request.POST.get('notes', '').strip()
            lat   = request.POST.get('latitude', '').strip()
            lng   = request.POST.get('longitude', '').strip()

            if not name or not phone:
                messages.error(request, "Ism va telefon raqamini kiriting.")
                form = OrderForm(request.POST)
                return render(request, 'checkout.html', {
                    'form': form, 'cart': cart, 'visible_categories': visible_categories
                })

            coords = f"{lat}, {lng}" if lat and lng else "belgilanmagan"
            order = Order.objects.create(
                first_name=name,
                phone=phone,
                region='Xarita',
                city='GPS',
                address=f"Xarita orqali: {coords}",
                notes=notes,
                total_price=cart.get_total_price(),
            )
            logger.info(f"Xarita rejimida buyurtma #{order.id} yaratildi (session: {cart.session_key})")
        else:
            form = OrderForm(request.POST)
            if form.is_valid():
                order = form.save(commit=False)
                order.total_price = cart.get_total_price()
                order.save()
                logger.info(f"Buyurtma #{order.id} muvaffaqiyatli yaratildi (session: {cart.session_key})")
            else:
                messages.error(request, "Iltimos, formani to'g'ri to'ldiring.")
                logger.warning(f"Checkout formasi noto'g'ri to'ldirildi (session: {cart.session_key})")
                return render(request, 'checkout.html', {
                    'form': form, 'cart': cart, 'visible_categories': visible_categories
                })

        cart_items = list(cart.cartitem_set.all())
        create_order_items(order, cart_items)
        send_order_notification(order, cart_items)
        cart.cartitem_set.all().delete()
        return redirect('order_success')

    form = OrderForm()
    return render(request, 'checkout.html', {
        'form': form,
        'cart': cart,
        'visible_categories': visible_categories
    })


def order_success(request):
    return render(request, 'order_success.html')


_CITIES = {
    'toshkent': [
        "Toshkent shahri", "Bektemir", "Chilonzor", "Hamza", "Mirobod",
        "Mirzo Ulug'bek", "Sergeli", "Shayxontohur", "Uchtepa",
        "Yakkasaroy", "Yunusobod", "Olmazor",
    ],
    'samarqand': [
        "Samarqand shahri", "Kattaqo'rg'on shahri", "Kattaqo'rg'on tumani",
        "Urgut", "Bulung'ur", "Jomboy", "Ishtixon", "Narpay", "Oqdaryo",
        "Pastdarg'om", "Paxtachi", "Payariq", "Qo'shrabot", "Tayloq", "Chelak",
    ],
    'navoiy': [
        "Navoiy shahri", "Zarafshon shahri", "Xatirchi", "Karmana",
        "Navbahor", "Nurota", "Qiziltepa", "Tomdi", "Uchquduq",
    ],
    'andijon': [
        "Andijon shahri", "Asaka", "Baliqchi", "Bo'ston", "Jalaquduq",
        "Xo'jaobod", "Izboskan", "Marhamat", "Oltinko'l", "Paxtaobod",
        "Qo'rg'ontepa", "Shahrixon", "Ulugnor",
    ],
    'fargona': [
        "Farg'ona shahri", "Qo'qon shahri", "Marg'ilon shahri", "Beshariq",
        "Bog'dod", "Buvayda", "Dang'ara", "Furqat", "Oltiariq", "Quva",
        "Rishton", "So'x", "Toshloq", "Uchko'prik", "O'zbekiston", "Yozyovon",
    ],
    'namangan': [
        "Namangan shahri", "Chortoq", "Chust", "Kosonsoy", "Mingbuloq",
        "Norin", "Pop", "To'raqo'rg'on", "Uychi", "Yangiqo'rg'on",
    ],
    'qashqadaryo': [
        "Qarshi shahri", "Shahrisabz shahri", "Chiroqchi", "Dehqonobod",
        "G'uzor", "Kamashi", "Kasbi", "Kitob", "Koson", "Muborak",
        "Nishon", "Qamashi", "Yakkabog'",
    ],
    'surxondaryo': [
        "Termiz shahri", "Angor", "Bandixon", "Boysun", "Denov",
        "Jarqo'rg'on", "Muzrabot", "Oltinsoy", "Qiziriq", "Qumqo'rg'on",
        "Sariosiyo", "Sherobod", "Sho'rchi", "Uzun",
    ],
    'xorazm': [
        "Urganch shahri", "Xiva shahri", "Bog'ot", "Gurlan",
        "Qo'shko'pir", "Shovot", "Tuproqqal'a", "Yangiariq", "Yangibozor",
    ],
    'buxoro': [
        "Buxoro shahri", "G'ijduvon", "Jondor", "Kogon shahri", "Olot",
        "Peshku", "Qorovulbozor", "Romitan", "Shofirkon", "Vobkent",
    ],
    'jizzax': [
        "Jizzax shahri", "Arnasoy", "Baxmal", "Do'stlik shahri",
        "G'allaorol", "Forish", "Mirzachul", "Paxtakor",
        "Sharof Rashidov", "Yangiobod", "Zarbdor", "Zomin",
    ],
    'sirdaryo': [
        "Guliston shahri", "Shirin shahri", "Boyovut", "Mirzaobod",
        "Oqoltin", "Sardoba", "Sayxunobod", "Xovos",
    ],
    'qoraqalpogiston': [
        "Nukus shahri", "Amudaryo", "Beruniy", "Chimboy", "Ellikkala",
        "Kegeyli", "Mo'ynoq", "Nukus tumani", "Qanliko'l", "Qo'ng'irot",
        "Shumanay", "Taxtako'pir", "To'rtko'l", "Xo'jayli",
    ],
}


def get_cities(request):
    region = request.GET.get('region', '').lower()
    if not region:
        return JsonResponse({'cities': [], 'message': 'Viloyat tanlanmadi'}, status=400)

    names = _CITIES.get(region, [])
    if not names:
        logger.warning(f"Noto'g'ri viloyat so'raldi: {region}")
        return JsonResponse({'cities': [], 'message': 'Viloyat topilmadi'}, status=404)

    return JsonResponse({'cities': [{'id': n, 'name': n} for n in names]})