import { Clock3, UserRound } from "lucide-react";
import { DIFFICULTIES, ingredientName } from "../recipes";

export default function RecipeContent({ recipe }) {
  if (!recipe) return null;
  return <section className="recipe-card">
    <div className="recipe-heading">
      <div><span className="eyebrow">食谱与做法</span><h3>{recipe.name}</h3><p>{recipe.description}</p></div>
      <div className="recipe-facts"><span><Clock3 size={15} />{recipe.total_time_minutes} 分钟</span><span><UserRound size={15} />{recipe.servings} 人份</span>{recipe.difficulty && <span>{DIFFICULTIES[recipe.difficulty] || recipe.difficulty}</span>}</div>
    </div>
    {recipe.nutrition && <div className="nutrition-strip"><span>{recipe.nutrition.basis === "per_100g" ? "每 100 克" : "整份食谱"}</span><strong>{recipe.nutrition.calories} kcal</strong><span>蛋白质 {recipe.nutrition.protein_g} g</span><span>碳水 {recipe.nutrition.carbs_g} g</span><span>脂肪 {recipe.nutrition.fat_g} g</span></div>}
    <div className="recipe-columns">
      <div><h4>准备食材</h4><ul>{recipe.ingredients?.map((item, i) => <li key={`${ingredientName(item)}-${i}`}><div><strong>{ingredientName(item)}</strong>{item.preparation && <small>{item.preparation}</small>}</div><span>{item.quantity} {item.unit}</span></li>)}</ul></div>
      <div><h4>烹饪步骤</h4><ol>{recipe.steps?.map((step) => <li key={step.number}>{step.instruction}</li>)}</ol></div>
    </div>
  </section>;
}
