# StockSense — Methodology Assumptions & Data Modeling Disclosures

**Project:** StockSense: Demand Forecasting & Inventory Risk Simulator  
**Dataset:** Walmart Recruiting - Store Sales Forecasting (Kaggle)  
**Author:** Analytics Engineering & Data Science  

---

## 1. Core Data Disclosures & Honesty Statement

The Walmart Store Sales dataset contains weekly historical revenue figures by Store and Department, alongside macro-economic and calendar indicators. It does **not** include unit quantities, inventory levels, supplier lead times, or product cost structures. 

To bridge this gap into an end-to-end inventory optimization simulation, specific domain-standard assumptions are applied. Every assumed parameter is explicitly documented below.

| Parameter / Aspect | Real Data Characteristic | StockSense Modeling Assumption | Business Rationale |
|---|---|---|---|
| **Demand Unit** | Weekly Sales in USD (`Weekly_Sales`) | Treated as weekly demand proxy (1 USD = 1 Demand Unit or base revenue proxy) | Retail series without unit volumes still exhibit cyclical demand variations and stockout dynamics. |
| **Negative Sales** | Negative sales exist (returns, accounting adjustments) | Flagged, clipped to 0 for inventory depletion, analyzed separately | Inventory cannot be depleted by negative quantities. Returns do not represent unconstrained consumer demand. |
| **Missing Markdowns** | MarkDown1–MarkDown5 have ~60% missing values (prior to Nov 2011) | Filled with `0.0`, with binary indicator features (`has_markdown`) added | Promotional markdowns were not tracked in earlier reporting periods; 0 indicates no promotional discount occurred. |
| **Supplier Lead Time** | Not present in Kaggle dataset | Discrete probability distribution: 1 week (50%), 2 weeks (35%), 3 weeks (15%) | Models realistic supplier variability and stochastic transit delays in retail replenishment. |
| **Holding Cost Rate ($h$)** | Not present | 20% annual carrying cost of unit inventory value ($h_{weekly} \approx 0.20 / 52 \approx 0.385\%$ per week) | Standard APICS / CSCMP benchmark for retail warehouse carrying costs (capital cost, shrinkage, insurance, warehousing). |
| **Stockout Penalty ($p$)** | Not present | Lost gross margin per unit short, assumed at $1.5 \times$ weekly holding cost or 30% margin equivalent | In competitive retail, out-of-stock events result in lost immediate sales and brand penalty. |
| **Fixed Order Cost ($K$)** | Not present | Assumed at \$50 per purchase order placement | Administrative and freight handling cost per replenishment batch. |
| **Starting Inventory ($I_0$)** | Not present | Initialized to 2 weeks of historical average demand ($\mu_{demand} \times 2$) | Prevents artificial initial stockouts in simulation burn-in. |
| **Backorders vs Lost Sales** | Not present | **Lost sales model** (unmet weekly demand is lost, not backordered) | Typical for physical grocery/general merchandise retail where customers substitute or purchase elsewhere. |

---

## 2. Inventory Policy: Periodic-Review $(s, S)$ Model

### Policy Mechanics
Replenishment reviews occur at weekly intervals ($R = 1 \text{ week}$):
1. **Receipt of In-Transit Orders:** Orders arriving in current week $t$ are added to on-hand inventory $I_t$.
2. **Customer Demand Realization:** Simulated demand $D_t$ occurs.
3. **Fulfillment:** Demand is fulfilled up to available on-hand stock ($S_t = \min(I_t, D_t)$). Unmet demand is lost ($L_t = \max(0, D_t - I_t)$).
4. **Inventory Position Evaluation:** 
   $$\text{Inventory Position } (IP_t) = I_t + \text{OnOrder}_t - \text{Backorders}_t$$
5. **Reorder Decision:** If $IP_t \le s$, generate an replenishment order of quantity $Q_t = S - IP_t$.
6. **Lead Time Draw:** An integer lead time $L \in \{1, 2, 3\}$ weeks is drawn from $P(L)$, scheduling delivery for week $t + L$.

---

## 3. Benchmark Formula vs. Monte Carlo Simulation

In classical inventory theory, under constant lead time $L$ and normally distributed demand with mean $\mu_D$ and standard deviation $\sigma_D$:
$$s = \mu_{LT} + z \cdot \sigma_{LT}$$
where:
- $\mu_{LT} = L \cdot \mu_D$
- $\sigma_{LT} = \sqrt{L \cdot \sigma_D^2 + \mu_D^2 \cdot \sigma_L^2}$ (accounting for variable lead time)
- $z$ is the standard normal critical value for target service level (e.g., $z = 1.645$ for 95%).

**Why Monte Carlo is Required:**
1. Retail demand distributions are heavily right-skewed and non-normal (demonstrated in EDA).
2. Lead times are stochastic and discrete.
3. The classical formula minimizes safety stock for a target cycle service level, but does **not** directly optimize the asymmetric cost trade-off between inventory holding cost and stockout penalties.
4. Monte Carlo outputs full risk distributions (P05, P50, P95 total cost, stockout probabilities).

---

## 4. Integrity and Reproducibility Commitments
- **Seed Setting:** All pseudo-random number generation in backtesting and simulation utilizes fixed seeds (`np.random.default_rng(42)`).
- **Time Leakage Prevention:** Feature engineering exclusively uses trailing windows and historical lags. No target encoding or global scaling spans future horizons.
- **Walk-Forward Cross-Validation:** Rolling origin backtesting preserves temporal ordering across 3 folds.
- **Reporting:** Every metric presented in the Power BI dashboard or executive summary is computed directly by executable pipeline scripts.
