from PIL import Image
import os

def generate_favicons(logo_path='LOGO.jpg', output_dir='static'):
    os.makedirs(output_dir, exist_ok=True)
    logo = Image.open(logo_path).convert('RGBA')

    sizes = {
        'favicon-16x16.png': (16, 16),
        'favicon-32x32.png': (32, 32),
        'apple-touch-icon.png': (180, 180),
        'android-chrome-192x192.png': (192, 192),
        'android-chrome-512x512.png': (512, 512),
    }

    for filename, size in sizes.items():
        img = logo.copy()
        img.thumbnail(size, Image.LANCZOS)
        # Kvadrat kanvas
        canvas = Image.new('RGBA', size, (255, 255, 255, 0))
        offset = ((size[0] - img.width) // 2, (size[1] - img.height) // 2)
        canvas.paste(img, offset, img)
        path = os.path.join(output_dir, filename)
        canvas.save(path, format='PNG', optimize=True)
        print(f"Saqlandi: {path} ({size[0]}x{size[1]})")

    # favicon.ico (16x16 va 32x32)
    img16 = logo.copy(); img16.thumbnail((16, 16), Image.LANCZOS)
    img32 = logo.copy(); img32.thumbnail((32, 32), Image.LANCZOS)
    c16 = Image.new('RGBA', (16, 16), (255, 255, 255, 0))
    c32 = Image.new('RGBA', (32, 32), (255, 255, 255, 0))
    c16.paste(img16, ((16 - img16.width)//2, (16 - img16.height)//2), img16)
    c32.paste(img32, ((32 - img32.width)//2, (32 - img32.height)//2), img32)
    ico_path = os.path.join(output_dir, 'favicon.ico')
    c16.convert('RGBA').save(ico_path, format='ICO', sizes=[(16, 16), (32, 32)])
    print(f"Saqlandi: {ico_path}")

if __name__ == '__main__':
    generate_favicons('LOGO.jpg', 'static')
