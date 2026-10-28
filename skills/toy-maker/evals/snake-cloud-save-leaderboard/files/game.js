const canvas = document.getElementById('board')
const ctx = canvas.getContext('2d')
const N = 16, S = canvas.width / N
const COLORS = { green: '#4caf50', pink: '#f48fb1', gold: '#ffc107' }
let snake, dir, food, score, timer
let best = Number(localStorage.getItem('best') || 0)
let skin = localStorage.getItem('skin') || 'green'
document.getElementById('best').textContent = best

function unlockSkins() {
  document.querySelector('[data-skin=pink]').disabled = best < 50
  document.querySelector('[data-skin=gold]').disabled = best < 100
}
unlockSkins()
document.querySelectorAll('[data-skin]').forEach(b => b.onclick = () => {
  skin = b.dataset.skin
  localStorage.setItem('skin', skin)
})

function reset() {
  snake = [{ x: 8, y: 8 }]; dir = { x: 1, y: 0 }; score = 0
  food = randFood()
  document.getElementById('over').hidden = true
}
function randFood() { return { x: Math.floor(Math.random() * N), y: Math.floor(Math.random() * N) } }

function tick() {
  const head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y }
  if (head.x < 0 || head.y < 0 || head.x >= N || head.y >= N || snake.some(p => p.x === head.x && p.y === head.y)) {
    return gameOver()
  }
  snake.unshift(head)
  if (head.x === food.x && head.y === food.y) {
    score += 10
    if (score > best) { best = score; localStorage.setItem('best', best) }
    document.getElementById('score').textContent = score
    document.getElementById('best').textContent = best
    food = randFood()
  } else snake.pop()
  draw()
}
function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.fillStyle = '#e53935'; ctx.fillRect(food.x * S, food.y * S, S, S)
  ctx.fillStyle = COLORS[skin]; snake.forEach(p => ctx.fillRect(p.x * S, p.y * S, S - 1, S - 1))
}
function gameOver() {
  clearInterval(timer)
  unlockSkins()
  document.getElementById('over').hidden = false
}
function start() { reset(); clearInterval(timer); timer = setInterval(tick, 120) }
document.getElementById('start').onclick = start
document.getElementById('again').onclick = start
document.addEventListener('keydown', e => {
  const m = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key]
  if (m) dir = { x: m[0], y: m[1] }
})
let sx, sy
canvas.addEventListener('touchstart', e => { sx = e.touches[0].clientX; sy = e.touches[0].clientY })
canvas.addEventListener('touchend', e => {
  const dx = e.changedTouches[0].clientX - sx, dy = e.changedTouches[0].clientY - sy
  dir = Math.abs(dx) > Math.abs(dy) ? { x: Math.sign(dx), y: 0 } : { x: 0, y: Math.sign(dy) }
})
