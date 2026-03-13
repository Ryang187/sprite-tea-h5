const state = {
  running: false,
  score: 0,
  combo: 0,
  timeLeft: 30,
  timerId: null,
  lastTapAt: 0,
};

const cupCount = document.getElementById("cupCount");
const comboCount = document.getElementById("comboCount");
const timeLeft = document.getElementById("timeLeft");
const progressBar = document.getElementById("progressBar");
const tapTarget = document.getElementById("tapTarget");
const startGame = document.getElementById("startGame");
const resetGame = document.getElementById("resetGame");
const resultCard = document.getElementById("resultCard");
const resultTitle = document.getElementById("resultTitle");
const resultText = document.getElementById("resultText");
const bonusBubble = document.getElementById("bonusBubble");

function render() {
  cupCount.textContent = String(Math.min(state.score, 100));
  comboCount.textContent = String(state.combo);
  timeLeft.textContent = state.timeLeft.toFixed(1);
  progressBar.style.width = `${Math.min((state.score / 100) * 100, 100)}%`;
}

function resetState() {
  state.running = false;
  state.score = 0;
  state.combo = 0;
  state.timeLeft = 30;
  state.lastTapAt = 0;
  if (state.timerId) {
    clearInterval(state.timerId);
    state.timerId = null;
  }
  resultCard.hidden = true;
  bonusBubble.hidden = true;
  bonusBubble.classList.remove("show");
  startGame.textContent = "开始 30 秒挑战";
  render();
}

function resultCopy(score) {
  if (score >= 100) {
    return {
      title: "你就是今天的冲杯天选之子",
      text: "30 秒内直接打满 100 杯，视觉上已经很有“全球牛碧之王”的气势了。",
    };
  }
  if (score >= 80) {
    return {
      title: "差一点就封王了",
      text: `你冲到了 ${score} 杯，已经非常接近百杯门槛，继续练手就能冲榜。`,
    };
  }
  if (score >= 50) {
    return {
      title: "财神潜力股",
      text: `你完成了 ${score} 杯，节奏很稳，适合继续推动到店挑战和消费冲榜。`,
    };
  }
  return {
    title: "先热个身，再来一局",
    text: `这次完成 ${score} 杯，建议多点几次试试连击暴击。`,
  };
}

function finishGame() {
  state.running = false;
  if (state.timerId) {
    clearInterval(state.timerId);
    state.timerId = null;
  }
  const result = resultCopy(state.score);
  resultTitle.textContent = result.title;
  resultText.textContent = result.text;
  resultCard.hidden = false;
  startGame.textContent = "再来一局";
}

function tick() {
  state.timeLeft = Math.max(0, state.timeLeft - 0.1);
  render();
  if (state.timeLeft <= 0 || state.score >= 100) {
    finishGame();
  }
}

function showBonus() {
  bonusBubble.hidden = false;
  bonusBubble.classList.remove("show");
  void bonusBubble.offsetWidth;
  bonusBubble.classList.add("show");
  window.setTimeout(() => {
    bonusBubble.hidden = true;
    bonusBubble.classList.remove("show");
  }, 900);
}

function handleTap() {
  if (!state.running) {
    return;
  }

  const now = Date.now();
  state.combo = now - state.lastTapAt < 700 ? state.combo + 1 : 1;
  state.lastTapAt = now;

  let gain = 1;
  if (state.combo > 0 && state.combo % 12 === 0) {
    gain += 5;
    showBonus();
  } else if (state.combo > 0 && state.combo % 6 === 0) {
    gain += 2;
  }

  state.score += gain;
  tapTarget.classList.add("pressed");
  window.setTimeout(() => tapTarget.classList.remove("pressed"), 120);
  render();

  if (state.score >= 100) {
    finishGame();
  }
}

function start() {
  if (state.running) {
    return;
  }
  resetState();
  state.running = true;
  startGame.textContent = "挑战进行中";
  state.timerId = window.setInterval(tick, 100);
}

startGame.addEventListener("click", start);
resetGame.addEventListener("click", resetState);
tapTarget.addEventListener("pointerdown", handleTap);

render();
