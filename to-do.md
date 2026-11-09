# To do

## Defects

- **Finding faces, and so where the words go, is unreliable.** The photo face detector missed cartoon faces, so a vision model now marks where faces are on each page. It still gets them wrong: it boxed the giant's whole body as his face (Jack p.7), so a page can be drawn again for nothing, or the words placed over a face it missed.

## Next assignment (agreed 2026-11-07)

- **Wallet with Stripe (test mode).** *Built 2026-11-07; the refund email waits on the Gmail app password.* Add funds, see the balance, and a history page listing every credit and debit with its cause. Each book costs $0.99, which replaces the one-a-day limit; admins and the unlimited list stay free. Unspent money goes back to the card straight away; a book that came out wrong is reviewed, and if approved its price goes back in the wallet. Requests appear in a Refunds tab in admin, the admin approves or denies them, and an email goes to the admin when one comes in.
- **One 20-page template for both stories.** Every page gets a fixed layout: where the art sits and where text is allowed to go.
- **A scene bible.** Draw each scene of both stories once, without the hero, and approve them. Each book edits the person's hero into those scenes. Test on 3 pages first (about 15¢, ask before running) for quality, time and cost.
- **Character bible in the database,** not as files.
- **Text never covers a face or anything the page needs.** Use the template's allowed text areas, and check where faces landed to pick the clear one.
- **Check every picture.** If one fails, draw it again, up to 3 tries in total, and keep the best.
- **Under 60 seconds** from Generate to a ready PDF: draw all pages at the same time, and maybe use a smaller size.
- **A progress bar that names the stage,** with thumbnails appearing as each picture finishes.
- **Little Red Riding Hood** as a second story on the same template.
- **Cleaner UI** pass at the end.
- **Run `storybook-review` before handing in,** once the professor shares it.

## Earlier ideas
- **Write the rest of the book.** Only pages 1–3 and About Me exist; the book should have 20 pages.
- **Draw the hero at the age they give.** The image prompts always say "child", so everyone is drawn as a kid. Use the age from the About Me field to decide. An adult is drawn as an adult. A child is drawn as a child, with their actual age in the prompt. A young person must never be made to look older, since that can offend.
- **Meet your hero first, then approve it.** "Plant the magic beans" draws only the hero sheet first ("meet your hero"). The person says whether it looks right, and can regenerate it if it doesn't, before any pages are drawn.
- **Have an AI check the photo before anything is drawn.** The face finder misses things: some photos had two people and the wrong one was drawn, and someone used Shrek as the hero. A vision model looks at the photo first and, if needed, sends back a message like "Use a picture with one real person, not a dog or a fictional character." That keeps out joke uploads and photos where it isn't clear who should be drawn.
- **Let people crop their photo.** Click the photo and crop it down to just the person's face, so it's clear who to draw.
- **Fix a page with feedback.** While flipping through the finished book, a page that looks off or weird can be sent back with "what's wrong with it?". That critique goes back to the image model with the page's prompt, and it draws a better version of that page.
- **Let people swap in their own look for side characters.** Every book uses the same default sheets, so the mother looks the same for everyone. If the reader has darker skin and the mother is very pale, that's odd. Option: upload a photo for a specific character (the mother now; later the giant, the goose and so on), and a one-off sheet is drawn for that book only. Each swapped character adds one sheet, about 2¢ (a book goes from about 12¢ to about 14¢). Maybe pets later.
