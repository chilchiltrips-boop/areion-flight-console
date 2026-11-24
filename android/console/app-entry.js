import {mobileFiles} from './mobile-files.js';
import {mountTouchDeck} from './touch-deck.js';

const bridge = window.AreionAndroid;

function shortcut(label, icon, launch, inMenu) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = inMenu ? 'nav android-device-action' : 'welcome-link';
  if (inMenu) {
    const image = document.createElement('img');
    image.src = new URL('../assets/console/' + icon, import.meta.url).href;
    image.alt = '';
    button.append(image);
  }
  const caption = document.createElement('span');
  caption.textContent = label;
  button.append(caption);
  button.addEventListener('click', () => {
    const menu = document.querySelector('#pages-menu');
    if (menu?.getAttribute('aria-expanded') === 'true') menu.click();
    launch();
  });
  return button;
}

if (bridge) {
  document.documentElement.classList.add('areion-android');
  window.AreionMobile = Object.freeze(mobileFiles(bridge));
  window.AreionTouchDeck = mountTouchDeck;
  if (!location.hash) history.replaceState(history.state, '', '#flight');
}

await import('../app.js');

if (bridge) {
  const nav = document.getElementById('console-pages');
  const launch = document.createElement('div');
  launch.className = 'android-welcome-actions';
  for (const [label, icon, action] of [
    ['Wi-Fi settings', 'nav-system.svg', () => bridge.openWifiSettings()],
    ['PC simulator pairing', 'launch-input.svg', () => bridge.openSimulator()]
  ]) {
    launch.append(shortcut(label, icon, action, false));
    nav.append(shortcut(label, icon, action, true));
  }
  document.getElementById('welcome-title').after(launch);
}
