# compile_pdf.py
import os
import re
import base64
import markdown
import asyncio
from playwright.async_api import async_playwright

# Custom CSS for the O'Reilly style typography and layout
CSS_STYLE = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&family=Noto+Sans+SC:wght@300;400;700&family=Fira+Code:wght@400;500&display=swap');

body {
    font-family: 'Inter', 'Noto Sans SC', sans-serif;
    font-size: 14px;
    line-height: 1.6;
    color: #222222;
    margin: 0;
    padding: 0;
}

/* Cover Page styling in premium O'Reilly look */
.cover-page {
    height: 100vh;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    align-items: center;
    padding: 60px 40px;
    box-sizing: border-box;
    text-align: center;
    page-break-after: always;
    background-color: #ffffff;
    border-top: 35px solid #8e2b2b; /* O'Reilly Red/Burgundy banner top */
    border-bottom: 20px solid #8e2b2b;
}

.cover-top {
    margin-top: 40px;
    width: 100%;
}

.cover-title {
    font-size: 38px;
    font-weight: 700;
    font-family: 'Georgia', serif;
    color: #111111;
    margin-bottom: 15px;
    line-height: 1.2;
}

.cover-subtitle {
    font-size: 16px;
    font-family: 'Georgia', serif;
    font-style: italic;
    color: #555555;
    max-width: 580px;
    line-height: 1.5;
    margin: 0 auto;
}

.cover-illustration-container {
    width: 320px;
    height: 320px;
    border: 1px solid #111111;
    display: flex;
    justify-content: center;
    align-items: center;
    background-color: #ffffff;
    box-shadow: 0 4px 12px rgba(0,0,0,0.06);
    overflow: hidden;
    margin: 30px 0;
}

.cover-illustration-image {
    width: 100%;
    height: 100%;
    object-fit: cover;
}

.cover-bottom {
    margin-bottom: 40px;
    width: 100%;
}

.cover-author {
    font-size: 18px;
    font-weight: 600;
    font-family: 'Inter', sans-serif;
    color: #222222;
    margin-bottom: 15px;
}

.cover-publisher {
    font-size: 13px;
    font-weight: bold;
    color: #8e2b2b;
    letter-spacing: 2px;
    text-transform: uppercase;
    font-family: 'Inter', sans-serif;
}

/* Table of Contents (TOC) page styling */
.toc-page {
    page-break-before: always;
    page-break-after: always;
    padding: 40px 20px;
    background-color: #ffffff;
}

.toc-title {
    font-size: 26px;
    font-weight: 700;
    color: #111111;
    border-bottom: 2px solid #111111;
    padding-bottom: 10px;
    margin-bottom: 45px;
    font-family: 'Georgia', serif;
    text-transform: uppercase;
    letter-spacing: 1px;
}

.toc-list {
    list-style-type: none;
    padding: 0;
    margin: 0;
}

.toc-chapter-item {
    margin-bottom: 25px;
}

.toc-chapter-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 15px;
}

.toc-chapter-title a {
    font-weight: 700;
    color: #111111;
    text-decoration: none;
    font-family: 'Inter', sans-serif;
}

.toc-chapter-title a:hover {
    text-decoration: underline;
    color: #8e2b2b;
}

.toc-sub-list {
    list-style-type: none;
    padding-left: 20px;
    margin-top: 8px;
}

.toc-sub-item {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 6px;
    font-size: 13px;
}

.toc-sub-title a {
    color: #555555;
    text-decoration: none;
    font-family: 'Inter', sans-serif;
}

.toc-sub-title a:hover {
    text-decoration: underline;
    color: #8e2b2b;
}

.toc-filler {
    flex-grow: 1;
    border-bottom: 1px dotted #bbbbbb;
    margin: 0 15px;
}

.toc-filler-sub {
    flex-grow: 1;
    border-bottom: 1px dashed #dddddd;
    margin: 0 15px;
}

.toc-page-num {
    font-weight: 600;
    color: #555555;
    font-family: 'Inter', sans-serif;
    font-size: 13px;
}

.chapter-container {
    page-break-before: always;
    padding: 20px 0;
}

h1 {
    font-size: 26px;
    font-weight: 700;
    color: #111111;
    border-bottom: 3px solid #111111;
    padding-bottom: 8px;
    margin-top: 0;
    margin-bottom: 30px;
    page-break-after: avoid;
}

h2 {
    font-size: 18px;
    font-weight: 600;
    color: #222222;
    margin-top: 30px;
    margin-bottom: 15px;
    page-break-after: avoid;
}

h3 {
    font-size: 15px;
    font-weight: 600;
    color: #333333;
    margin-top: 20px;
    margin-bottom: 10px;
    page-break-after: avoid;
}

p {
    margin-top: 0;
    margin-bottom: 15px;
    text-align: justify;
}

/* Lists styling */
ul, ol {
    margin-top: 0;
    margin-bottom: 15px;
    padding-left: 20px;
}

li {
    margin-bottom: 6px;
}

/* Code and blockquote styling */
pre {
    background-color: #f7f7f9;
    border: 1px solid #e1e1e8;
    border-radius: 4px;
    padding: 12px 16px;
    font-family: 'Fira Code', 'Courier New', Courier, monospace;
    font-size: 12px;
    overflow-x: auto;
    margin-top: 15px;
    margin-bottom: 15px;
    page-break-inside: avoid;
}

code {
    font-family: 'Fira Code', 'Courier New', Courier, monospace;
    font-size: 12px;
    background-color: #f7f7f9;
    color: #d72b3f;
    padding: 2px 4px;
    border-radius: 3px;
}

pre code {
    background-color: transparent;
    color: inherit;
    padding: 0;
    border-radius: 0;
}

blockquote {
    border-left: 4px solid #111111;
    padding-left: 15px;
    margin-left: 0;
    margin-right: 0;
    margin-top: 15px;
    margin-bottom: 15px;
    color: #555555;
    font-style: italic;
    page-break-inside: avoid;
}

/* Table styling */
table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 20px;
    margin-bottom: 20px;
    font-size: 13px;
    page-break-inside: avoid;
}

th, td {
    border: 1px solid #dddddd;
    padding: 8px 10px;
    text-align: left;
}

th {
    background-color: #f5f5f5;
    font-weight: 600;
}
"""

HEADER_TEMPLATE = """
<div style="font-size: 8px; width: 100%; display: flex; justify-content: space-between; padding: 0 40px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #555555; border-bottom: 0.5px solid #dddddd; padding-bottom: 3px; box-sizing: border-box;">
    <span>FORWARD DEPLOYED ENGINEERING HANDBOOK</span>
    <span></span>
</div>
"""

FOOTER_TEMPLATE = """
<div style="font-size: 8px; width: 100%; display: flex; justify-content: space-between; padding: 0 40px; font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #555555; border-top: 0.5px solid #dddddd; padding-top: 3px; box-sizing: border-box;">
    <span>Confidential - For Review Only</span>
    <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
</div>
"""

def convert_md_to_html(md_text):
    extensions = ['tables', 'fenced_code', 'nl2br']
    return markdown.markdown(md_text, extensions=extensions)

def get_chapter_number(filename):
    match = re.search(r'chapter(\d+)', filename)
    return int(match.group(1)) if match else 999

def get_base64_image(image_path):
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode('utf-8')
    except Exception as e:
        print(f"Error loading image {image_path}: {e}")
        return ""

def process_chapter_content(md_content, chapter_num):
    processed_lines = []
    subheadings = []
    sub_count = 1
    
    in_code_block = False
    
    # Process line by line to inject explicit anchor IDs for TOC linking, skipping code blocks
    for line in md_content.split('\n'):
        # Toggle code block state when encountering fenced backticks
        if line.strip().startswith('```'):
            in_code_block = not in_code_block
            processed_lines.append(line)
            continue
            
        if not in_code_block:
            if line.startswith('# '):
                title = line.replace('# ', '').strip()
                processed_lines.append(f'<h1 id="chapter-{chapter_num}">{title}</h1>')
            elif line.startswith('## '):
                subtitle = line.replace('## ', '').strip()
                sub_id = f"chapter-{chapter_num}-sub-{sub_count}"
                subheadings.append((sub_id, subtitle))
                processed_lines.append(f'<h2 id="{sub_id}">{subtitle}</h2>')
                sub_count += 1
            else:
                processed_lines.append(line)
        else:
            processed_lines.append(line)
            
    processed_md = '\n'.join(processed_lines)
    return processed_md, subheadings

def build_full_html(chapters_dir, cover_data, toc_title="Table of Contents", chapter_label="Chapter"):
    # Correct numerical sorting of chapters
    files = sorted(
        [f for f in os.listdir(chapters_dir) if f.endswith('.md') and f.startswith('chapter')],
        key=get_chapter_number
    )
    
    # Base64 encode the cover image
    base64_img = get_base64_image(cover_data['image_path'])
    img_src = f"data:image/png;base64,{base64_img}" if base64_img else ""
    
    # Generate cover page HTML
    html_out = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>{CSS_STYLE}</style>
</head>
<body>
    <div class="cover-page">
        <div class="cover-top">
            <div class="cover-title">{cover_data['title']}</div>
            <div class="cover-subtitle">{cover_data['subtitle']}</div>
        </div>
        <div class="cover-illustration-container">
            <img src="{img_src}" class="cover-illustration-image" alt="Book Illustration">
        </div>
        <div class="cover-bottom">
            <!-- Author and publisher removed -->
        </div>
    </div>
"""

    toc_structure = []
    chapter_html_blocks = []
    
    # Parse each chapter, rewrite headers with matching HTML anchor IDs, collect TOC entries
    for file_name in files:
        file_path = os.path.join(chapters_dir, file_name)
        num = get_chapter_number(file_name)
        print(f"Parsing: {file_name}")
        with open(file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        
        # Extract SVG blocks and replace with placeholders to protect them from markdown parsing
        svg_pattern = re.compile(r'(<svg.*?</svg>)', re.DOTALL)
        svg_blocks = svg_pattern.findall(md_content)
        
        temp_md = md_content
        placeholders = []
        for i, svg in enumerate(svg_blocks):
            placeholder = f"<!-- SVG_PLACEHOLDER_{i} -->"
            placeholders.append((placeholder, svg))
            temp_md = temp_md.replace(svg, placeholder, 1)
        
        # Rewrite headers with IDs and extract subheadings list
        processed_md, subheadings = process_chapter_content(temp_md, num)
        
        # Extract main title (first line processed H1)
        h1_match = re.search(r'<h1 id="chapter-\d+">(.+?)</h1>', processed_md)
        chapter_title = h1_match.group(1) if h1_match else f"Chapter {num}"
        
        toc_structure.append((num, chapter_title, subheadings))
        
        chapter_html = convert_md_to_html(processed_md)
        
        # Restore raw SVG blocks, removing any surrounding paragraph tags created by the markdown parser
        for placeholder, svg in placeholders:
            p_placeholder = f"<p>{placeholder}</p>"
            if p_placeholder in chapter_html:
                chapter_html = chapter_html.replace(p_placeholder, svg)
            else:
                chapter_html = chapter_html.replace(placeholder, svg)
        
        chapter_html_blocks.append(f'<div class="chapter-container">{chapter_html}</div>\n')
        
    # Generate the interactive Table of Contents (TOC) page HTML
    html_out += f"""
    <div class="toc-page">
        <div class="toc-title">{toc_title}</div>
        <ul class="toc-list">
    """
    
    for num, title, subheadings in toc_structure:
        # Chapter row
        label_formatted = f"第 {num} 章" if chapter_label == "第" else f"Chapter {num}"
        
        html_out += f"""
            <li class="toc-chapter-item">
                <div class="toc-chapter-row">
                    <span class="toc-chapter-title"><a href="#chapter-{num}">{title}</a></span>
                    <span class="toc-filler"></span>
                    <span class="toc-page-num">{label_formatted}</span>
                </div>
        """
        
        # Subsections nesting
        if subheadings:
            html_out += '<ul class="toc-sub-list">'
            for sub_id, sub_title in subheadings:
                html_out += f"""
                    <li class="toc-sub-item">
                        <span class="toc-sub-title"><a href="#{sub_id}">{sub_title}</a></span>
                        <span class="toc-filler-sub"></span>
                    </li>
                """
            html_out += '</ul>'
            
        html_out += '</li>'
        
    html_out += """
        </ul>
    </div>
    """
    
    # Append the chapter HTML contents
    for block in chapter_html_blocks:
        html_out += block
        
    html_out += "</body>\n</html>"
    return html_out

async def generate_pdf(html_content, output_pdf_path):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        await page.set_viewport_size({"width": 800, "height": 1130})
        await page.set_content(html_content)
        await page.evaluate("document.fonts.ready")
        
        await page.pdf(
            path=output_pdf_path,
            format="A4",
            display_header_footer=True,
            header_template=HEADER_TEMPLATE,
            footer_template=FOOTER_TEMPLATE,
            margin={
                "top": "80px",
                "bottom": "80px",
                "left": "60px",
                "right": "60px"
            }
        )
        print(f"Successfully compiled PDF to: {output_pdf_path}")
        await browser.close()

def main():
    cover_image = "cover_giraffe.png"
    
    # English Version configuration
    cover_en = {
        "image_path": cover_image,
        "title": "Forward Deployed Engineering",
        "subtitle": "Bridging Core Products and Client Realities in the Enterprise & AI Era",
        "author": "Nicole Li & Antigravity AI",
        "publisher": "O'REILLY MEDIA, INC. / DRAFT COPY"
    }
    
    # Chinese Version configuration
    cover_zh = {
        "image_path": cover_image,
        "title": "前向部署工程实战指南",
        "subtitle": "企业级与 AI 时代下核心产品与客户落地的桥梁",
        "author": "Nicole Li & Antigravity AI",
        "publisher": "O'REILLY 媒体出版社 / 评审草案"
    }
    
    # Compile English Book
    print("Compiling English version...")
    html_en = build_full_html("book_en", cover_en, toc_title="Table of Contents", chapter_label="Chapter")
    with open("book_en.html", "w", encoding="utf-8") as f:
        f.write(html_en)
        
    # Compile Chinese Book
    print("Compiling Chinese version...")
    html_zh = build_full_html("book_zh", cover_zh, toc_title="目  录", chapter_label="第")
    with open("book_zh.html", "w", encoding="utf-8") as f:
        f.write(html_zh)
        
    # Run Playwright PDF rendering
    print("Rendering PDFs using Playwright Chromium...")
    asyncio.run(generate_pdf(html_en, "fde_handbook_en.pdf"))
    asyncio.run(generate_pdf(html_zh, "fde_handbook_zh.pdf"))
    print("All books built successfully!")

if __name__ == "__main__":
    main()
