from flask import Flask, render_template, request, redirect, url_for
import os
import datetime
import backtest_main_strategy

app = Flask(__name__)

# Lưu trạng thái lệnh và lịch sử giao dịch (giả lập)
current_positions = []
trade_history = []

@app.route("/")
def index():
    return render_template(
        "index.html",
        positions=current_positions,
        history=trade_history,
        backtest_result=None,
        start_date=None,
        end_date=None
    )

@app.route("/backtest", methods=["POST"])
def backtest():
    start_date = request.form.get("start_date")
    end_date = request.form.get("end_date")
    # Chạy backtest với khoảng thời gian được chọn
    results = backtest_main_strategy.run_backtest_with_time_range(start_date, end_date)
    return render_template(
        "index.html",
        positions=current_positions,
        history=trade_history,
        backtest_result=results,
        start_date=start_date,
        end_date=end_date
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
