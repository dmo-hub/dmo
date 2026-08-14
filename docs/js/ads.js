// Sponsored-ad rotation — single source for every page that ships the
// ad markup (#ad-float / .ad-inline / #ad-box with data-ad-* hooks).
// เพิ่ม/ลบสินค้า: แก้ ADS ตรงนี้ที่เดียว ทุกหน้าอัพเดตพร้อมกัน
(() => {
  const ADS = [
    {img:'img/ads/dmo-dungeon-service.jpg', label:'service',
     link:'https://web.facebook.com/groups/244114362448211/posts/3185424211650530'},
    {img:'img/ads/726548819_2462184690968077_7780691861906989290_n.jpg', label:'promo',
     link:'https://web.facebook.com/photo/?fbid=2462184687634744&set=gm.3185826914943593&idorvanity=244114362448211'},
    {img:'img/ads/761633298_2505508689969010_7397997845874297130_n.jpg', label:'promo',
     link:'https://web.facebook.com/photo/?fbid=2505508686635677&set=gm.3235723446620606&idorvanity=244114362448211'},
  ];

  const float = document.getElementById('ad-float');
  const box = document.getElementById('ad-box');
  if (!float || !box) return; // page has no ad markup

  // apply ad ไปยัง scope ที่กำหนด (root = document ทั้งหน้า หรือ #ad-box เฉพาะ popup)
  const applyAd = (i, root = document) => {
    const ad = ADS[i];
    root.querySelectorAll('[data-ad-img]').forEach(el => { el.src = ad.img; el.alt = ad.label; });
    root.querySelectorAll('[data-ad-link]').forEach(el => { el.href = ad.link; });
    root.querySelectorAll('[data-ad-label]').forEach(el => { el.textContent = ad.label; });
  };

  // เริ่มต้น: สุ่ม 1 ทั้งหน้า (floating + inline + box)
  let cur = Math.floor(Math.random() * ADS.length);
  applyAd(cur);

  // popup เปิด → auto สลับรูปในกล่องทุก 3.5 วิ (เฉพาะ #ad-box, ไม่แตะ floating thumb)
  let slideTimer = null;
  const startSlide = () => {
    if (ADS.length < 2) return;
    slideTimer = setInterval(() => {
      cur = (cur + 1) % ADS.length;
      applyAd(cur, box);
    }, 3500);
  };
  const stopSlide = () => { clearInterval(slideTimer); slideTimer = null; };

  document.getElementById('ad-close').addEventListener('click', () => { float.hidden = true; });
  const openBox = () => { applyAd(cur, box); box.classList.add('open'); startSlide(); };
  const closeBox = () => { box.classList.remove('open'); stopSlide(); };
  document.getElementById('ad-thumb').addEventListener('click', openBox);
  document.getElementById('ad-x').addEventListener('click', closeBox);
  box.addEventListener('click', e => { if (e.target === box) closeBox(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeBox(); });
})();
